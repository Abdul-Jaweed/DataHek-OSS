"""Quality evaluation — per-dimension scores and state thresholds."""
import unittest

from datahek.context.quality import evaluate_quality
from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    ColumnSchema,
    FreshnessReport,
    GovernanceContext,
    GrainStatement,
    GranularityContext,
    JoinEdge,
    OntologyConcept,
    OntologyContext,
    ProfileContext,
    ProvenanceSource,
    QualityState,
    SchemaContext,
    TableSchema,
    TrustLevel,
    ValidationStatus,
)


def _envelope(kind, provenance=ProvenanceSource.DATABASE,
              validation=ValidationStatus.NOT_REQUIRED):
    return ArtifactEnvelope(kind=kind, schema_version=1, provenance=provenance,
                            trust=TrustLevel.STRUCTURAL, validation=validation,
                            confidence=1.0, generated_at="t")


def _schema(columns=("id", "amount")):
    return SchemaContext(
        envelope=_envelope(ArtifactKind.SCHEMA), database="d", schema="public",
        tables=(TableSchema(name="orders", columns=tuple(
            ColumnSchema(name=c, data_type="integer" if c == "id" else "numeric",
                         nullable=True, ordinal=i) for i, c in enumerate(columns))),),
        schema_hash="h")


def _profiles():
    from datahek.contracts.context import ColumnProfile

    return ProfileContext(
        envelope=_envelope(ArtifactKind.PROFILE),
        tables={"orders": (ColumnProfile(name="id", row_count=10, null_ratio=0.0),
                           ColumnProfile(name="amount", row_count=10, null_ratio=0.0))})


def _ontology(validation=ValidationStatus.PENDING, confidence=0.6):
    return OntologyContext(
        envelope=_envelope(ArtifactKind.ONTOLOGY, ProvenanceSource.LLM, validation),
        concepts=(OntologyConcept(name="Order", kind="entity", maps_to=("orders",),
                                  attributes=(), provenance=ProvenanceSource.LLM,
                                  validation=validation, confidence=confidence),),
        relationships=())


class TestQuality(unittest.TestCase):
    def test_empty_schema_is_insufficient(self):
        empty = SchemaContext(envelope=_envelope(ArtifactKind.SCHEMA), database="d",
                              schema="public", tables=(), schema_hash="h")
        report = evaluate_quality(schema=empty)
        self.assertEqual(report.state, QualityState.INSUFFICIENT)
        self.assertEqual(report.schema_completeness, 0.0)

    def test_schema_without_profiles_is_partial(self):
        report = evaluate_quality(schema=_schema())
        self.assertEqual(report.state, QualityState.PARTIAL)
        self.assertEqual(report.profiling_coverage, 0.0)

    def test_full_context_is_sufficient(self):
        report = evaluate_quality(schema=_schema(), profiles=_profiles(),
                                  topology=None, granularity=None)
        self.assertEqual(report.state, QualityState.SUFFICIENT)
        self.assertEqual(report.profiling_coverage, 1.0)

    def test_validated_proposals_raise_state(self):
        report = evaluate_quality(
            schema=_schema(), profiles=_profiles(),
            topology=self._topology(), granularity=self._granularity(),
            governance=self._governance(), freshness=self._freshness(),
            ontology=_ontology(validation=ValidationStatus.APPROVED, confidence=0.9))
        self.assertEqual(report.human_validation, 1.0)
        self.assertEqual(report.state, QualityState.VALIDATED)

    @staticmethod
    def _topology():
        from datahek.contracts.context import TopologyContext

        return TopologyContext(
            envelope=_envelope(ArtifactKind.TOPOLOGY),
            edges=(JoinEdge(left="orders.id", right="orders.id", kind="fk",
                            cardinality="1:1", fanout_risk="none",
                            provenance=ProvenanceSource.DATABASE, confidence=1.0),))

    @staticmethod
    def _granularity():
        return GranularityContext(
            envelope=_envelope(ArtifactKind.GRANULARITY),
            grains=(GrainStatement(table="orders", statement="1 row = 1 Order",
                                   confidence=0.9),),
            metric_grains=())

    @staticmethod
    def _governance():
        return GovernanceContext(
            envelope=_envelope(ArtifactKind.GOVERNANCE, ProvenanceSource.SYSTEM),
            sensitive_columns=(), restricted_columns=(), allowed_operations=("SELECT",),
            masking_policy_refs=(), permission_version="p1")

    @staticmethod
    def _freshness():
        return FreshnessReport(state="fresh", age_seconds=0, schema_hash_matches=True,
                               permission_version_matches=True)

    def test_dimensions_reflect_artifacts(self):
        report = evaluate_quality(schema=_schema(), profiles=_profiles(),
                                  topology=self._topology(),
                                  granularity=self._granularity(), ontology=_ontology(),
                                  governance=self._governance(),
                                  freshness=self._freshness())
        self.assertEqual(report.relationship_coverage, 1.0)
        self.assertAlmostEqual(report.granularity_confidence, 0.9)
        self.assertEqual(report.governance_coverage, 1.0)
        self.assertEqual(report.freshness_score, 1.0)
        self.assertEqual(report.semantic_confidence, 0.6)


if __name__ == "__main__":
    unittest.main()
