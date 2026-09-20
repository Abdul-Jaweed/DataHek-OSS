"""ContextBuildJob — staged build with retries, degradation, and versioned publish."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from datahek.context.graph.builder import SchemaGraphBuilder
from datahek.context.graph.memory import InMemoryGraphRepository
from datahek.context.jobs.build_context import ContextBuildJob
from datahek.context.profiler import SchemaProfiler
from datahek.context.registry import ContextRegistryService
from datahek.contracts.connections import Connection
from datahek.contracts.context import (
    ArtifactKind,
    LifecycleState,
    OntologyConcept,
    OntologyContext,
    ProvenanceSource,
    ValidationStatus,
)
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind, ReadOnlyLevel
from datahek.defaults.context_store import SqliteContextRegistry, SqliteContextStore
from datahek.engine.executor import Engine, ProviderRegistry
from datahek.engine.schema import ColumnMeta, SchemaCatalog, SchemaService, TableMeta
from datahek.kernel.context import RequestContext

_CATALOG = SchemaCatalog(source="c1:appdb", tables=[
    TableMeta(name="orders", columns=[
        ColumnMeta(name="id", data_type="integer", nullable=False, ordinal=0,
                   is_primary_key=True),
        ColumnMeta(name="amount", data_type="double precision", ordinal=1)],
        primary_key=("id",), row_count=100),
])


class _FakeProvider:
    provider_id = "fake"
    capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, dialect="fake",
                                         read_only=ReadOnlyLevel.STRUCTURAL,
                                         max_result_rows=1000)

    def __init__(self, fail_introspect=False):
        self._fail = fail_introspect

    async def connect(self, connection):
        return object()

    async def introspect(self, ctx, connection, source):
        if self._fail:
            raise RuntimeError("database down")
        return _CATALOG

    async def compile_and_execute(self, client, plan, ctx):
        aggregates = plan.nodes[0].aggregates
        values = {"n": 100}
        for agg in aggregates:
            if agg.alias == "n":
                continue
            if agg.alias.startswith("nn_"):
                values[agg.alias] = 100
            elif agg.alias.startswith("dc_"):
                values[agg.alias] = 100
            elif agg.alias.startswith("mn_"):
                values[agg.alias] = "1"
            elif agg.alias.startswith("mx_"):
                values[agg.alias] = "99"
            elif agg.alias.startswith("av_"):
                values[agg.alias] = 12.5
        return {"columns": [{"name": agg.alias, "type": "Any"} for agg in aggregates],
                "rows": [tuple(values[agg.alias] for agg in aggregates)]}

    async def ping(self, client):
        return {"ok": True}

    async def close(self, client):
        pass


class _FakeEnricher:
    async def propose(self, schema, taxonomy, *, metrics=()):
        from datahek.contracts.context import ArtifactEnvelope, TrustLevel

        envelope = ArtifactEnvelope(
            kind=ArtifactKind.ONTOLOGY, schema_version=1,
            provenance=ProvenanceSource.LLM, trust=TrustLevel.PROPOSED,
            validation=ValidationStatus.PENDING, confidence=0.6,
            generated_at="2026-09-21T00:00:00Z")
        return OntologyContext(
            envelope=envelope,
            concepts=(OntologyConcept(name="Order", kind="entity", maps_to=("orders",),
                                      attributes=(), provenance=ProvenanceSource.LLM,
                                      validation=ValidationStatus.PENDING, confidence=0.6),),
            relationships=())


class _BrokenEnricher:
    async def propose(self, schema, taxonomy, *, metrics=()):
        raise RuntimeError("model down")


class _DownGraphRepo(InMemoryGraphRepository):
    async def health_check(self):
        return False


def _conn():
    return Connection(id="conn1", name="fake", provider="fake", org_id="default",
                      project_id="default", database="appdb")


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        path = str(Path(self._tmp.name) / "ctx.db")
        self.registry = SqliteContextRegistry(path)
        self.store = SqliteContextStore(path)
        self.registry_service = ContextRegistryService(self.registry, self.store)
        self.ctx = RequestContext(source="cli")
        self.provider = _FakeProvider()
        provider_registry = ProviderRegistry()
        provider_registry.register(self.provider)

    def tearDown(self):
        self._tmp.cleanup()

    def call(self, coro):
        return asyncio.run(coro)

    def job(self, *, enricher=None, graph_repo=None, profiler=True):
        return ContextBuildJob(
            schema_service=SchemaService(),
            registry_service=self.registry_service,
            profiler=SchemaProfiler(self._provider_engine()) if profiler else None,
            enricher=enricher,
            graph_builder=SchemaGraphBuilder(graph_repo or InMemoryGraphRepository()),
        )

    def _provider_engine(self):
        registry = ProviderRegistry()
        registry.register(self.provider)
        return Engine(registry)


class TestBuildJob(_Base):
    def test_full_build_publishes_active_v1(self):
        result = self.call(self.job(enricher=_FakeEnricher()).run(
            self.ctx, _conn(), self.provider))
        self.assertEqual(result.state, LifecycleState.ACTIVE.value)
        self.assertEqual(result.version, 1)
        self.assertIsNotNone(result.context_id)
        names = [stage.name for stage in result.stages]
        self.assertEqual(names, ["INTROSPECT", "PROFILE", "TOPOLOGY", "GRANULARITY",
                                 "TAXONOMY", "ENRICH", "GRAPH_BUILD", "QUALITY", "PUBLISH"])
        self.assertTrue(all(stage.status in ("ok", "skipped", "degraded")
                            for stage in result.stages))
        record = self.call(self.registry.get(self.ctx, result.context_id))
        self.assertEqual(record.artifact_kinds,
                         (ArtifactKind.GRANULARITY, ArtifactKind.ONTOLOGY,
                          ArtifactKind.PROFILE, ArtifactKind.SCHEMA,
                          ArtifactKind.TAXONOMY, ArtifactKind.TOPOLOGY))

    def test_rebuild_creates_version_2_and_supersedes(self):
        first = self.call(self.job().run(self.ctx, _conn(), self.provider))
        second = self.call(self.job().run(self.ctx, _conn(), self.provider,
                                          skip_if_current=False))
        self.assertEqual(second.version, 2)
        previous = self.call(self.registry.get(self.ctx, first.context_id))
        self.assertEqual(previous.state, LifecycleState.SUPERSEDED)

    def test_skip_if_current_short_circuits(self):
        self.call(self.job().run(self.ctx, _conn(), self.provider))
        result = self.call(self.job().run(self.ctx, _conn(), self.provider))
        self.assertEqual(result.state, "current")
        self.assertIsNone(result.context_id)
        self.assertEqual(result.stages[-1].name, "INTROSPECT")

    def test_introspection_failure_aborts_without_publish(self):
        broken = _FakeProvider(fail_introspect=True)
        result = self.call(self.job().run(self.ctx, _conn(), broken))
        self.assertEqual(result.state, "failed")
        self.assertIsNone(result.context_id)
        self.assertEqual(result.stages[0].status, "failed")
        self.assertIsNone(self.call(self.registry.active(
            self.ctx, connection_id="conn1", scope="connection")))

    def test_graph_unavailable_degrades_but_publishes(self):
        result = self.call(self.job(graph_repo=_DownGraphRepo()).run(
            self.ctx, _conn(), self.provider))
        self.assertTrue(result.degraded)
        self.assertEqual(result.state, LifecycleState.ACTIVE.value)
        graph_stage = next(s for s in result.stages if s.name == "GRAPH_BUILD")
        self.assertEqual(graph_stage.status, "degraded")

    def test_enricher_failure_degrades_but_publishes(self):
        result = self.call(self.job(enricher=_BrokenEnricher()).run(
            self.ctx, _conn(), self.provider))
        self.assertEqual(result.state, LifecycleState.ACTIVE.value)
        enrich = next(s for s in result.stages if s.name == "ENRICH")
        self.assertEqual(enrich.status, "degraded")
        self.assertTrue(any("enrich" in warning for warning in result.warnings))

    def test_no_profile_path_still_publishes(self):
        result = self.call(self.job(profiler=False).run(self.ctx, _conn(), self.provider))
        self.assertEqual(result.state, LifecycleState.ACTIVE.value)
        profile_stage = next(s for s in result.stages if s.name == "PROFILE")
        self.assertEqual(profile_stage.status, "skipped")
        record = self.call(self.registry.get(self.ctx, result.context_id))
        self.assertNotIn(ArtifactKind.PROFILE, record.artifact_kinds)


if __name__ == "__main__":
    unittest.main()
