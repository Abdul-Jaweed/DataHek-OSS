"""SQLite context registry/store + registry service — versioning and lifecycle."""
import asyncio
import dataclasses
import tempfile
import unittest
from pathlib import Path

from datahek.context.registry import ContextRegistryService
from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    ColumnSchema,
    FreshnessReport,
    LifecycleState,
    OntologyConcept,
    OntologyContext,
    ProvenanceSource,
    QualityReport,
    QualityState,
    SchemaContext,
    TableSchema,
    TrustLevel,
    ValidationStatus,
)
from datahek.defaults.context_store import SqliteContextRegistry, SqliteContextStore
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode


def _envelope(kind, provenance=ProvenanceSource.DATABASE,
              validation=ValidationStatus.NOT_REQUIRED, trust=TrustLevel.STRUCTURAL):
    return ArtifactEnvelope(kind=kind, schema_version=1, provenance=provenance, trust=trust,
                            validation=validation, confidence=1.0,
                            generated_at="2026-09-21T00:00:00Z")


def _schema(hash_value="h1"):
    return SchemaContext(
        envelope=_envelope(ArtifactKind.SCHEMA), database="d", schema="public",
        tables=(TableSchema(name="orders", columns=(
            ColumnSchema(name="id", data_type="integer", nullable=False, ordinal=0),)),),
        schema_hash=hash_value)


def _ontology():
    return OntologyContext(
        envelope=_envelope(ArtifactKind.ONTOLOGY, ProvenanceSource.LLM,
                           ValidationStatus.PENDING, TrustLevel.PROPOSED),
        concepts=(OntologyConcept(name="Order", kind="entity", maps_to=("orders",),
                                  attributes=(), provenance=ProvenanceSource.LLM,
                                  validation=ValidationStatus.PENDING, confidence=0.6),),
        relationships=())


def _quality(state=QualityState.SUFFICIENT):
    return QualityReport(state=state, schema_completeness=1.0, profiling_coverage=1.0,
                         semantic_confidence=0.6, relationship_coverage=0.0,
                         granularity_confidence=0.9, human_validation=0.0,
                         freshness_score=1.0, governance_coverage=0.0)


def _freshness():
    return FreshnessReport(state="fresh", age_seconds=0, schema_hash_matches=True,
                           permission_version_matches=True)


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self._tmp.name) / "ctx.db")
        self.registry = SqliteContextRegistry(self.path)
        self.store = SqliteContextStore(self.path)
        self.service = ContextRegistryService(self.registry, self.store)
        self.ctx = RequestContext(source="cli")

    def tearDown(self):
        self._tmp.cleanup()

    def call(self, coro):
        return asyncio.run(coro)

    def publish(self, **kwargs):
        return self.call(self.service.publish(
            self.ctx, connection_id="conn1", scope="connection",
            schema_hash=kwargs.pop("schema_hash", "h1"),
            artifacts=kwargs.pop("artifacts", {ArtifactKind.SCHEMA: _schema()}),
            quality=kwargs.pop("quality", _quality()),
            freshness=kwargs.pop("freshness", _freshness()), **kwargs))


class TestPublishing(_Base):
    def test_first_publish_is_version_1_active(self):
        record = self.publish()
        self.assertEqual(record.version, 1)
        self.assertEqual(record.state, LifecycleState.ACTIVE)
        self.assertIsNone(record.supersedes)
        active = self.call(self.registry.active(self.ctx, connection_id="conn1",
                                                scope="connection"))
        self.assertEqual(active.context_id, record.context_id)

    def test_second_publish_supersedes_previous(self):
        first = self.publish()
        second = self.publish(schema_hash="h2")
        self.assertEqual(second.version, 2)
        self.assertEqual(second.previous_version, 1)
        self.assertEqual(second.supersedes, first.context_id)
        previous = self.call(self.registry.get(self.ctx, first.context_id))
        self.assertEqual(previous.state, LifecycleState.SUPERSEDED)
        versions = self.call(self.registry.versions(
            self.ctx, connection_id="conn1", scope="connection"))
        self.assertEqual([r.version for r in versions], [2, 1])

    def test_require_validation_parks_llm_proposals(self):
        record = self.publish(
            artifacts={ArtifactKind.SCHEMA: _schema(), ArtifactKind.ONTOLOGY: _ontology()},
            require_validation=True)
        self.assertEqual(record.state, LifecycleState.PENDING_VALIDATION)

    def test_default_publishes_active_with_proposals(self):
        record = self.publish(
            artifacts={ArtifactKind.SCHEMA: _schema(), ArtifactKind.ONTOLOGY: _ontology()})
        self.assertEqual(record.state, LifecycleState.ACTIVE)
        self.assertEqual(record.provenance_summary.get("llm"), 1)


class TestStore(_Base):
    def test_artifact_round_trip(self):
        record = self.publish()
        stored = self.call(self.store.get(self.ctx, record.context_id, ArtifactKind.SCHEMA))
        self.assertEqual(stored, _schema())

    def test_artifact_requires_known_record(self):
        with self.assertRaises(DatahekError) as cm:
            self.call(self.store.put(self.ctx, "ctx-missing", _schema()))
        self.assertEqual(cm.exception.code, ErrorCode.NOT_FOUND)

    def test_tenant_isolation(self):
        record = self.publish()
        other = RequestContext(source="cli", organization_id="other")
        self.assertIsNone(self.call(self.registry.get(other, record.context_id)))
        self.assertEqual(self.call(self.registry.find(other, connection_id="conn1")), [])
        self.assertIsNone(self.call(
            self.store.get(other, record.context_id, ArtifactKind.SCHEMA)))

    def test_register_rejects_foreign_org_record(self):
        record = self.publish()
        foreign = dataclasses.replace(record, org_id="other")
        with self.assertRaises(DatahekError) as cm:
            self.call(self.registry.register(self.ctx, foreign))
        self.assertEqual(cm.exception.code, ErrorCode.FORBIDDEN)


class TestLifecycleAndInvalidation(_Base):
    def test_illegal_state_transition_rejected(self):
        record = self.publish()
        with self.assertRaises(DatahekError) as cm:
            self.call(self.registry.set_state(self.ctx, record.context_id,
                                              LifecycleState.VALIDATED, "no"))
        self.assertEqual(cm.exception.code, ErrorCode.VALIDATION)

    def test_invalidate_marks_active_stale(self):
        record = self.publish()
        count = self.call(self.service.invalidate(self.ctx, connection_id="conn1",
                                                  reason="schema changed"))
        self.assertEqual(count, 1)
        updated = self.call(self.registry.get(self.ctx, record.context_id))
        self.assertEqual(updated.state, LifecycleState.STALE)
        self.assertIsNone(self.call(self.registry.active(
            self.ctx, connection_id="conn1", scope="connection")))

    def test_is_current_compares_hash(self):
        self.publish()
        self.assertTrue(self.call(self.service.is_current(
            self.ctx, connection_id="conn1", scope="connection", schema_hash="h1")))
        self.assertFalse(self.call(self.service.is_current(
            self.ctx, connection_id="conn1", scope="connection", schema_hash="h2")))


if __name__ == "__main__":
    unittest.main()
