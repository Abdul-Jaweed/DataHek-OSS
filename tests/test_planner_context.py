"""Planner context integration — compiled ContextPackage replaces ad-hoc assembly (FR-019/020)."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from datahek.contracts.connections import Connection
from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    ColumnProfile,
    ColumnSchema,
    FreshnessReport,
    GovernanceContext,
    GrainStatement,
    GranularityContext,
    JoinEdge,
    ProfileContext,
    ProvenanceSource,
    QualityReport,
    QualityState,
    SchemaContext,
    TableSchema,
    TopologyContext,
    TrustLevel,
    ValidationStatus,
)
from datahek.contracts.models import ModelProvider, ModelRequest, ModelResponse
from datahek.context.compiler import PackageContextCompiler
from datahek.context.composer import BudgetContextComposer
from datahek.context.registry import ContextRegistryService
from datahek.context.retriever import ContextRetrieverService
from datahek.defaults.context_store import SqliteContextRegistry, SqliteContextStore
from datahek.engine.planner import Planner
from datahek.engine.schema import _CatalogEntry, ColumnMeta, SchemaCatalog, SchemaService, TableMeta
from datahek.kernel.context import RequestContext


def _catalog():
    return SchemaCatalog(
        source="c1:default",
        tables=[TableMeta(name="traces", columns=[
            ColumnMeta(name="service", data_type="String"),
            ColumnMeta(name="status", data_type="String"),
        ])],
    )


class _FakeModel(ModelProvider):
    def __init__(self, response: str):
        self._response = response
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(content=self._response)

    async def stream(self, request: ModelRequest):
        yield self._response


class _FakeProvider:
    provider_id = "clickhouse"

    class capabilities:
        dialect = "clickhouse"


class _BoomRetriever:
    async def retrieve(self, *args, **kwargs):
        raise RuntimeError("store down")


class _TinyComposer:
    async def compose(self, ctx, retrieved, runtime):
        return await BudgetContextComposer().compose(ctx, retrieved, runtime, budget_tokens=1)


def _plan_json():
    return {
        "nodes": [{
            "type": "ReadNode", "source": "events", "columns": ["customer_id"],
            "aggregates": [{"function": "count", "column": "*", "alias": "n"}],
            "group_by": ["customer_id"], "limit": 10,
        }]
    }


def _trace_plan_json():
    return {
        "nodes": [{
            "type": "ReadNode", "source": "traces", "columns": ["service"],
            "aggregates": [{"function": "count", "column": "*", "alias": "n"}],
            "group_by": ["service"], "limit": 10,
        }]
    }


def _envelope(kind, provenance=ProvenanceSource.DATABASE, trust=TrustLevel.STRUCTURAL):
    return ArtifactEnvelope(kind=kind, schema_version=1, provenance=provenance, trust=trust,
                            validation=ValidationStatus.NOT_REQUIRED, confidence=1.0,
                            generated_at="2026-09-21T00:00:00Z")


def _schema():
    return SchemaContext(
        envelope=_envelope(ArtifactKind.SCHEMA), database="d", schema="public",
        tables=(TableSchema(name="events", columns=(
            ColumnSchema(name="id", data_type="int", nullable=False, ordinal=0),
            ColumnSchema(name="customer_id", data_type="int", nullable=True, ordinal=1),
            ColumnSchema(name="amount", data_type="float", nullable=True, ordinal=2)),
            primary_key=("id",)),
            TableSchema(name="customers", columns=(
                ColumnSchema(name="id", data_type="int", nullable=False, ordinal=0),
                ColumnSchema(name="name", data_type="text", nullable=True, ordinal=1)),
                primary_key=("id",))),
        schema_hash="h1")


def _topology():
    return TopologyContext(
        envelope=_envelope(ArtifactKind.TOPOLOGY),
        edges=(JoinEdge(left="events.customer_id", right="customers.id", kind="fk",
                        cardinality="N:1", fanout_risk="low",
                        provenance=ProvenanceSource.DATABASE, confidence=1.0),))


def _granularity():
    return GranularityContext(
        envelope=_envelope(ArtifactKind.GRANULARITY),
        grains=(GrainStatement(table="events", statement="1 row of events = 1 event",
                               source=ProvenanceSource.SYSTEM,
                               validation=ValidationStatus.PENDING, confidence=0.9),),
        metric_grains=())


def _governance():
    return GovernanceContext(
        envelope=_envelope(ArtifactKind.GOVERNANCE, ProvenanceSource.SYSTEM, TrustLevel.SYSTEM),
        sensitive_columns=(), restricted_columns=("customers.name",),
        allowed_operations=("SELECT",), masking_policy_refs=(), permission_version="p1")


def _quality():
    return QualityReport(state=QualityState.SUFFICIENT, schema_completeness=1.0,
                         profiling_coverage=0.6, semantic_confidence=0.6,
                         relationship_coverage=0.6, granularity_confidence=0.9,
                         human_validation=0.0, freshness_score=1.0,
                         governance_coverage=1.0)


def _freshness():
    return FreshnessReport(state="fresh", age_seconds=0, schema_hash_matches=True,
                           permission_version_matches=True)


class _Base(unittest.TestCase):
    def setUp(self):
        self.ctx = RequestContext(source="api")
        self.conn = Connection(id="c1", name="ch", provider="clickhouse",
                               org_id="default", project_id="default")
        self.provider = _FakeProvider()
        self.service = SchemaService()
        self.service._entries["c1:default"] = _CatalogEntry(catalog=_catalog(),
                                                            fetched_at=__import__("time").time())
        self._tmp = tempfile.TemporaryDirectory()
        path = str(Path(self._tmp.name) / "ctx.db")
        registry = SqliteContextRegistry(path)
        store = SqliteContextStore(path)
        self.retriever = ContextRetrieverService(registry, store)
        asyncio.run(ContextRegistryService(registry, store).publish(
            self.ctx, connection_id="c1", scope="connection", schema_hash="h1",
            artifacts={
                ArtifactKind.SCHEMA: _schema(),
                ArtifactKind.PROFILE: ProfileContext(
                    envelope=_envelope(ArtifactKind.PROFILE),
                    tables={"events": (ColumnProfile(name="amount", row_count=10,
                                                     null_ratio=0.0),)}),
                ArtifactKind.TOPOLOGY: _topology(),
                ArtifactKind.GRANULARITY: _granularity(),
                ArtifactKind.GOVERNANCE: _governance(),
            },
            quality=_quality(), freshness=_freshness()))

    def tearDown(self):
        self._tmp.cleanup()

    def _planner(self, model, **kwargs):
        kwargs.setdefault("retriever", self.retriever)
        kwargs.setdefault("composer", BudgetContextComposer())
        kwargs.setdefault("compiler", PackageContextCompiler())
        return Planner(model=model, schema_service=self.service, **kwargs)

    def _prompt(self, model):
        return model.requests[0]["messages"][-1]["content"]


class TestPlannerWithContext(_Base):
    def test_prompt_uses_package_schema_and_grain(self):
        model = _FakeModel(json.dumps(_plan_json()))
        result = asyncio.run(self._planner(model).plan("count events by customers", self.ctx,
                                                      self.conn, self.provider))
        self.assertIsNotNone(result.plan)
        prompt = self._prompt(model)
        self.assertIn("events", prompt)
        self.assertIn("customer_id:int", prompt)
        self.assertIn("1 row of events = 1 event", prompt)
        self.assertIn("customers.name", prompt)
        self.assertIn("events.customer_id = customers.id", prompt)
        self.assertNotIn("traces", prompt)

    def test_package_schema_validates_plan_without_live_catalog(self):
        self.service._entries.clear()
        model = _FakeModel(json.dumps(_plan_json()))
        result = asyncio.run(self._planner(model).plan("events", self.ctx,
                                                      self.conn, self.provider))
        self.assertIsNotNone(result.plan)
        self.assertEqual(result.plan.nodes[0].source, "events")

    def test_missing_record_falls_back_to_live_catalog(self):
        model = _FakeModel(json.dumps(_trace_plan_json()))
        self.service._entries["other:default"] = self.service._entries["c1:default"]
        other = Connection(id="other", name="ch", provider="clickhouse",
                           org_id="default", project_id="default")
        result = asyncio.run(self._planner(model).plan("error count", self.ctx,
                                                      other, self.provider))
        self.assertIsNotNone(result.plan)
        self.assertIn("traces", self._prompt(model))

    def test_retriever_failure_degrades_to_live_catalog(self):
        model = _FakeModel(json.dumps(_trace_plan_json()))
        planner = self._planner(model, retriever=_BoomRetriever())
        result = asyncio.run(planner.plan("error count", self.ctx, self.conn, self.provider))
        self.assertIsNotNone(result.plan)
        self.assertIn("traces", self._prompt(model))

    def test_insufficient_package_returns_clarification_without_model_call(self):
        model = _FakeModel(json.dumps(_plan_json()))
        planner = self._planner(model, composer=_TinyComposer())
        result = asyncio.run(planner.plan("events by customer", self.ctx,
                                          self.conn, self.provider))
        self.assertIsNone(result.plan)
        self.assertIn("context", result.clarification.lower())
        self.assertEqual(model.requests, [])

    def test_context_disabled_uses_live_catalog(self):
        model = _FakeModel(json.dumps(_trace_plan_json()))
        planner = Planner(model=model, schema_service=self.service)
        result = asyncio.run(planner.plan("error count", self.ctx, self.conn, self.provider))
        self.assertIsNotNone(result.plan)
        self.assertIn("traces", self._prompt(model))


if __name__ == "__main__":
    unittest.main()


class TestValueHintsInContextSummary(_Base):
    def _publish_with_hints(self):
        from datahek.contracts.context import ColumnProfile, ProfileContext

        registry = self.retriever._registry
        store = self.retriever._store
        service = ContextRegistryService(registry, store)
        asyncio.run(service.publish(
            self.ctx, connection_id="c1", scope="connection", schema_hash="h1",
            artifacts={
                ArtifactKind.SCHEMA: _schema(),
                ArtifactKind.PROFILE: ProfileContext(
                    envelope=_envelope(ArtifactKind.PROFILE),
                    tables={"events": (ColumnProfile(
                        name="customer_id", row_count=10, null_ratio=0.0,
                        distinct_count=2,
                        top_values=(("payment", 6), ("checkout", 4)),
                        role_candidates=("dimension",)),)}),
                ArtifactKind.GOVERNANCE: _governance(),
            },
            quality=_quality(), freshness=_freshness()))

    def test_example_values_reach_the_prompt(self):
        self._publish_with_hints()
        model = _FakeModel(json.dumps(_plan_json()))
        result = asyncio.run(self._planner(model).plan("count events", self.ctx,
                                                      self.conn, self.provider))
        self.assertIsNotNone(result.plan)
        prompt = self._prompt(model)
        self.assertIn("customer_id:int (e.g. payment, checkout)", prompt)

    def test_no_hints_without_profiles(self):
        model = _FakeModel(json.dumps(_plan_json()))
        asyncio.run(self._planner(model).plan("count events", self.ctx, self.conn,
                                              self.provider))
        self.assertIn("customer_id:int", self._prompt(model))
        self.assertNotIn("(e.g.", self._prompt(model).split("Restricted")[0])
