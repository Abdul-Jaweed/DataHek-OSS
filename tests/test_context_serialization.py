"""Serialization round-trips for artifacts, records, and packages (JSON-safe)."""
import json
import unittest

from datahek.context.serialization import (
    artifact_from_dict,
    artifact_to_dict,
    package_from_dict,
    package_to_dict,
    record_from_dict,
    record_to_dict,
)
from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    CapabilityContext,
    ColumnProfile,
    ColumnSchema,
    ContextBudget,
    ContextPackage,
    ContextRecord,
    FreshnessReport,
    GovernanceContext,
    GrainStatement,
    GranularityContext,
    JoinEdge,
    LifecycleState,
    MetricGrain,
    OntologyConcept,
    OntologyContext,
    OntologyRelationship,
    ProfileContext,
    ProvenanceEntry,
    ProvenanceSource,
    QualityReport,
    QualityState,
    SchemaContext,
    SemanticsSummary,
    SkillRef,
    TableSchema,
    TaxonomyContext,
    TaxonomyNode,
    ToolRef,
    TopologyContext,
    TrustLevel,
    ValidationStatus,
)


def _envelope(kind, provenance=ProvenanceSource.DATABASE, trust=TrustLevel.STRUCTURAL,
              validation=ValidationStatus.NOT_REQUIRED, confidence=1.0):
    return ArtifactEnvelope(kind=kind, schema_version=1, provenance=provenance, trust=trust,
                            validation=validation, confidence=confidence,
                            generated_at="2026-09-21T00:00:00Z", warnings=("w",))


def _quality():
    return QualityReport(state=QualityState.SUFFICIENT, schema_completeness=1.0,
                         profiling_coverage=0.8, semantic_confidence=0.6,
                         relationship_coverage=0.5, granularity_confidence=0.9,
                         human_validation=0.0, freshness_score=1.0,
                         governance_coverage=0.0, details={"note": "x"})


def _freshness():
    return FreshnessReport(state="fresh", age_seconds=0, schema_hash_matches=True,
                           permission_version_matches=True,
                           refresh_due_at="2026-09-22T00:00:00Z")


def _artifacts():
    table = TableSchema(name="orders", columns=(
        ColumnSchema(name="id", data_type="integer", nullable=False, ordinal=0,
                     default=None, is_primary_key=True, is_foreign_key=False,
                     references=None, comment="pk"),),
        primary_key=("id",), foreign_keys=(("customer_id", "customers.id"),),
        indexes=("idx",), comment="t", estimated_rows=10)
    return [
        SchemaContext(envelope=_envelope(ArtifactKind.SCHEMA), database="d", schema="public",
                      tables=(table,), schema_hash="h"),
        ProfileContext(envelope=_envelope(ArtifactKind.PROFILE), tables={
            "orders": (ColumnProfile(name="id", row_count=10, null_ratio=0.0, distinct_count=10,
                                     distinct_estimated=False, uniqueness_ratio=1.0,
                                     min_value="1", max_value="10", avg_value=5.5,
                                     min_length=None, max_length=None, top_values=(),
                                     role_candidates=("identifier",),
                                     role_confidence={"identifier": 1.0}, sensitive=False),)},
            sampled=False, sample_size=None),
        TaxonomyContext(envelope=_envelope(ArtifactKind.TAXONOMY), nodes=(
            TaxonomyNode(path=("D", "orders", "Identifier"), members=("orders.id",),
                         node_kind="category", provenance=ProvenanceSource.SYSTEM,
                         validation=ValidationStatus.PENDING, confidence=0.9),)),
        OntologyContext(envelope=_envelope(ArtifactKind.ONTOLOGY, ProvenanceSource.LLM,
                                           TrustLevel.PROPOSED, ValidationStatus.PENDING, 0.6),
                        concepts=(OntologyConcept(name="Order", kind="entity", maps_to=("orders",),
                                                  attributes=("orders.id",),
                                                  provenance=ProvenanceSource.LLM,
                                                  validation=ValidationStatus.PENDING,
                                                  confidence=0.6, description="d",
                                                  synonyms=("purchase",)),),
                        relationships=(OntologyRelationship(subject="Order", predicate="contains",
                                                            object="Item", kind="contains",
                                                            provenance=ProvenanceSource.LLM,
                                                            validation=ValidationStatus.PENDING,
                                                            confidence=0.6),)),
        TopologyContext(envelope=_envelope(ArtifactKind.TOPOLOGY), edges=(
            JoinEdge(left="orders.customer_id", right="customers.id", kind="fk",
                     cardinality="N:1", fanout_risk="low",
                     provenance=ProvenanceSource.DATABASE, confidence=1.0),),
            join_paths={"a->b": (("orders.customer_id=customers.id",),)}),
        GranularityContext(envelope=_envelope(ArtifactKind.GRANULARITY), grains=(
            GrainStatement(table="orders", statement="1 row of orders = 1 Order",
                           qualifier=None, entity="Order", source=ProvenanceSource.SYSTEM,
                           validation=ValidationStatus.PENDING, confidence=0.9),),
            metric_grains=(MetricGrain(metric="revenue", valid_at=("1 row of orders = 1 Order",),
                                       caveat=None),)),
        GovernanceContext(envelope=_envelope(ArtifactKind.GOVERNANCE, ProvenanceSource.SYSTEM,
                                             TrustLevel.SYSTEM),
                          sensitive_columns=("orders.card",), restricted_columns=(),
                          allowed_operations=("SELECT",), masking_policy_refs=(),
                          permission_version="p1"),
        CapabilityContext(envelope=_envelope(ArtifactKind.CAPABILITY), skills=(
            SkillRef(name="sql.basic", version="1", precondition=None),),
            tools=(ToolRef(name="schema.inspect", kind="tool", scopes=("read",)),),
            providers=("postgres",)),
    ]


class TestArtifactRoundTrip(unittest.TestCase):
    def test_every_v1_artifact_round_trips_through_json(self):
        for artifact in _artifacts():
            data = json.loads(json.dumps(artifact_to_dict(artifact)))
            restored = artifact_from_dict(artifact.envelope.kind, data)
            self.assertEqual(restored, artifact, artifact.envelope.kind)


class TestRecordAndPackageRoundTrip(unittest.TestCase):
    def test_record_round_trip(self):
        record = ContextRecord(
            context_id="ctx1", org_id="default", project_id="default",
            connection_id="conn1", scope="connection", version=2,
            state=LifecycleState.ACTIVE, schema_hash="h",
            created_at="t1", updated_at="t2", artifact_kinds=(ArtifactKind.SCHEMA,),
            quality=_quality(), freshness=_freshness(),
            previous_version=1, supersedes="ctx0", validated_at=None,
            provenance_summary={"database": 3}, notes="n")
        data = json.loads(json.dumps(record_to_dict(record)))
        self.assertEqual(record_from_dict(data), record)

    def test_package_round_trip(self):
        schema, profile, taxonomy, ontology, topology, granularity, governance, capability = \
            _artifacts()
        package = ContextPackage(
            context_id="ctx1", org_id="default", project_id="default", connection_id="conn1",
            version=2, schema_hash="h", purpose="sql.planner", generated_at="t",
            schema=schema.tables, profile=profile.tables, taxonomy=taxonomy.nodes,
            ontology=ontology.concepts, topology=topology.edges,
            granularity=granularity.grains,
            semantics=SemanticsSummary(metrics=({"name": "revenue"},), dimensions=("orders.id",),
                                       identifiers=("orders.id",),
                                       temporal_fields=("orders.created_at",)),
            governance=governance, capabilities=capability,
            quality=_quality(), freshness=_freshness(),
            provenance=(ProvenanceEntry(field="schema", source=ProvenanceSource.DATABASE,
                                        confidence=1.0,
                                        validation=ValidationStatus.NOT_REQUIRED, note=""),),
            trust=TrustLevel.STRUCTURAL,
            budget=ContextBudget(tokens_estimate=100, dropped_sections=("profile",)),
            degraded=("graph",))
        data = json.loads(json.dumps(package_to_dict(package)))
        self.assertEqual(package_from_dict(data), package)


if __name__ == "__main__":
    unittest.main()
