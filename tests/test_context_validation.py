"""Human semantic validation — approve/edit/reject proposals and publish a validated version."""
import unittest
import tempfile
from pathlib import Path
from dataclasses import replace

from datahek.context.registry import ContextRegistryService
from datahek.context.validation import (
    ContextValidationService,
    PendingItem,
    ValidationDecision,
)
from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    ColumnSchema,
    FreshnessReport,
    GrainStatement,
    GranularityContext,
    LifecycleState,
    OntologyConcept,
    OntologyContext,
    OntologyRelationship,
    ProvenanceSource,
    QualityReport,
    QualityState,
    SchemaContext,
    TableSchema,
    TaxonomyContext,
    TaxonomyNode,
    TrustLevel,
    ValidationStatus,
)
from datahek.defaults.context_store import SqliteContextRegistry, SqliteContextStore
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode

import asyncio


def _envelope(kind, provenance=ProvenanceSource.DATABASE,
              validation=ValidationStatus.NOT_REQUIRED, trust=TrustLevel.STRUCTURAL):
    return ArtifactEnvelope(kind=kind, schema_version=1, provenance=provenance, trust=trust,
                            validation=validation, confidence=1.0,
                            generated_at="2026-09-21T00:00:00Z")


def _schema():
    return SchemaContext(
        envelope=_envelope(ArtifactKind.SCHEMA), database="d", schema="public",
        tables=(TableSchema(name="orders", columns=(
            ColumnSchema(name="id", data_type="integer", nullable=False, ordinal=0),)),),
        schema_hash="h1")


def _ontology():
    return OntologyContext(
        envelope=_envelope(ArtifactKind.ONTOLOGY, ProvenanceSource.LLM,
                           ValidationStatus.PENDING, TrustLevel.PROPOSED),
        concepts=(OntologyConcept(name="Order", kind="entity", maps_to=("orders",),
                                  attributes=(), provenance=ProvenanceSource.LLM,
                                  validation=ValidationStatus.PENDING, confidence=0.6,
                                  description="a purchase"),),
        relationships=(OntologyRelationship(subject="Customer", predicate="places",
                                            object="Order", kind="places",
                                            provenance=ProvenanceSource.LLM,
                                            validation=ValidationStatus.PENDING,
                                            confidence=0.6),))


def _taxonomy():
    return TaxonomyContext(
        envelope=_envelope(ArtifactKind.TAXONOMY, ProvenanceSource.SYSTEM,
                           ValidationStatus.PENDING),
        nodes=(TaxonomyNode(path=("D", "orders", "Identifier"), members=("orders.id",),
                            node_kind="category", provenance=ProvenanceSource.SYSTEM,
                            validation=ValidationStatus.PENDING, confidence=0.9),))


def _granularity():
    return GranularityContext(
        envelope=_envelope(ArtifactKind.GRANULARITY, ProvenanceSource.SYSTEM,
                           ValidationStatus.PENDING),
        grains=(GrainStatement(table="orders", statement="1 row of orders = 1 Order",
                               entity="Order", source=ProvenanceSource.SYSTEM,
                               validation=ValidationStatus.PENDING, confidence=0.9),),
        metric_grains=())


def _quality():
    return QualityReport(state=QualityState.SUFFICIENT, schema_completeness=1.0,
                         profiling_coverage=1.0, semantic_confidence=0.6,
                         relationship_coverage=0.0, granularity_confidence=0.9,
                         human_validation=0.0, freshness_score=1.0,
                         governance_coverage=0.0)


def _freshness():
    return FreshnessReport(state="fresh", age_seconds=0, schema_hash_matches=True,
                           permission_version_matches=True)


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        path = str(Path(self._tmp.name) / "ctx.db")
        self.registry = SqliteContextRegistry(path)
        self.store = SqliteContextStore(path)
        self.registry_service = ContextRegistryService(self.registry, self.store)
        self.service = ContextValidationService(self.registry, self.store,
                                                self.registry_service)
        self.ctx = RequestContext(source="cli")

    def tearDown(self):
        self._tmp.cleanup()

    def call(self, coro):
        return asyncio.run(coro)

    def publish(self, artifacts=None):
        return self.call(self.registry_service.publish(
            self.ctx, connection_id="conn1", scope="connection", schema_hash="h1",
            artifacts=artifacts or {
                ArtifactKind.SCHEMA: _schema(),
                ArtifactKind.ONTOLOGY: _ontology(),
                ArtifactKind.TAXONOMY: _taxonomy(),
                ArtifactKind.GRANULARITY: _granularity(),
            },
            quality=_quality(), freshness=_freshness()))


class TestPendingListing(_Base):
    def test_lists_pending_items_across_artifacts(self):
        self.publish()
        pending = self.call(self.service.list_pending(self.ctx, connection_id="conn1"))
        labels = {(item.kind, item.section, item.index, item.label) for item in pending}
        self.assertIn((ArtifactKind.ONTOLOGY, "concepts", 0, "Order"), labels)
        self.assertIn((ArtifactKind.ONTOLOGY, "relationships", 0, "Customer places Order"),
                      labels)
        self.assertIn((ArtifactKind.TAXONOMY, "nodes", 0, "D / orders / Identifier"), labels)
        self.assertIn((ArtifactKind.GRANULARITY, "grains", 0, "orders"), labels)
        self.assertEqual(len(pending), 4)
        self.assertTrue(all(item.provenance for item in pending))

    def test_list_pending_without_active_record(self):
        self.assertEqual(self.call(
            self.service.list_pending(self.ctx, connection_id="missing")), [])


class TestDecisions(_Base):
    def test_approve_concept_publishes_validated_version(self):
        first = self.publish()
        record = self.call(self.service.apply(
            self.ctx, connection_id="conn1",
            decisions=(ValidationDecision(ArtifactKind.ONTOLOGY, 0, "approve",
                                          section="concepts"),)))
        self.assertEqual(record.version, 2)
        self.assertEqual(record.state, LifecycleState.ACTIVE)
        previous = self.call(self.registry.get(self.ctx, first.context_id))
        self.assertEqual(previous.state, LifecycleState.SUPERSEDED)
        artifact = self.call(self.store.get(self.ctx, record.context_id, ArtifactKind.ONTOLOGY))
        concept = artifact.concepts[0]
        self.assertEqual(concept.validation, ValidationStatus.APPROVED)
        self.assertEqual(concept.provenance, ProvenanceSource.HUMAN_VALIDATED)
        self.assertGreater(record.quality.human_validation, 0.0)
        self.assertEqual(record.provenance_summary.get("llm"), 1)

    def test_edit_concept_applies_patch(self):
        self.publish()
        record = self.call(self.service.apply(
            self.ctx, connection_id="conn1",
            decisions=(ValidationDecision(ArtifactKind.ONTOLOGY, 0, "edit",
                                          section="concepts",
                                          patch={"description": "a confirmed purchase",
                                                 "synonyms": ["sale"]}),)))
        artifact = self.call(self.store.get(self.ctx, record.context_id, ArtifactKind.ONTOLOGY))
        concept = artifact.concepts[0]
        self.assertEqual(concept.validation, ValidationStatus.EDITED)
        self.assertEqual(concept.provenance, ProvenanceSource.HUMAN_VALIDATED)
        self.assertEqual(concept.description, "a confirmed purchase")
        self.assertEqual(concept.synonyms, ("sale",))

    def test_reject_relationship_marks_rejected(self):
        self.publish()
        record = self.call(self.service.apply(
            self.ctx, connection_id="conn1",
            decisions=(ValidationDecision(ArtifactKind.ONTOLOGY, 0, "reject",
                                          section="relationships"),)))
        artifact = self.call(self.store.get(self.ctx, record.context_id, ArtifactKind.ONTOLOGY))
        relationship = artifact.relationships[0]
        self.assertEqual(relationship.validation, ValidationStatus.REJECTED)
        self.assertEqual(relationship.provenance, ProvenanceSource.LLM)

    def test_approve_grain_and_taxonomy(self):
        self.publish()
        record = self.call(self.service.apply(
            self.ctx, connection_id="conn1",
            decisions=(ValidationDecision(ArtifactKind.GRANULARITY, 0, "approve"),
                       ValidationDecision(ArtifactKind.TAXONOMY, 0, "approve"))))
        grain_artifact = self.call(self.store.get(self.ctx, record.context_id,
                                                  ArtifactKind.GRANULARITY))
        self.assertEqual(grain_artifact.grains[0].validation,
                         ValidationStatus.APPROVED)
        self.assertEqual(grain_artifact.grains[0].source,
                         ProvenanceSource.HUMAN_VALIDATED)
        taxonomy_artifact = self.call(self.store.get(self.ctx, record.context_id,
                                                     ArtifactKind.TAXONOMY))
        self.assertEqual(taxonomy_artifact.nodes[0].validation,
                         ValidationStatus.APPROVED)

    def test_edit_grain_statement(self):
        self.publish()
        record = self.call(self.service.apply(
            self.ctx, connection_id="conn1",
            decisions=(ValidationDecision(ArtifactKind.GRANULARITY, 0, "edit",
                                          patch={"statement": "1 row = 1 order (confirmed)"}),)))
        artifact = self.call(self.store.get(self.ctx, record.context_id,
                                            ArtifactKind.GRANULARITY))
        self.assertEqual(artifact.grains[0].statement, "1 row = 1 order (confirmed)")

    def test_invalid_decision_inputs_rejected(self):
        self.publish()
        with self.assertRaises(DatahekError) as cm:
            self.call(self.service.apply(
                self.ctx, connection_id="conn1",
                decisions=(ValidationDecision(ArtifactKind.ONTOLOGY, 9, "approve",
                                              section="concepts"),)))
        self.assertEqual(cm.exception.code, ErrorCode.VALIDATION)
        with self.assertRaises(DatahekError):
            self.call(self.service.apply(
                self.ctx, connection_id="conn1",
                decisions=(ValidationDecision(ArtifactKind.ONTOLOGY, 0, "edit",
                                              section="concepts",
                                              patch={"name": "Hacked"}),)))
        with self.assertRaises(DatahekError):
            self.call(self.service.apply(
                self.ctx, connection_id="conn1",
                decisions=(ValidationDecision(ArtifactKind.TAXONOMY, 0, "edit",
                                              patch={"members": ["x"]}),)))
        with self.assertRaises(DatahekError):
            self.call(self.service.apply(
                self.ctx, connection_id="conn1",
                decisions=(ValidationDecision(ArtifactKind.ONTOLOGY, 0, "maybe",
                                              section="concepts"),)))

    def test_apply_without_active_record_raises(self):
        with self.assertRaises(DatahekError) as cm:
            self.call(self.service.apply(
                self.ctx, connection_id="missing",
                decisions=(ValidationDecision(ArtifactKind.ONTOLOGY, 0, "approve",
                                              section="concepts"),)))
        self.assertEqual(cm.exception.code, ErrorCode.NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
