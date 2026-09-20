"""Composition and compilation — budgeted degradation and deterministic packages."""
import asyncio
import unittest

from datahek.context.compiler import PackageContextCompiler
from datahek.context.composer import BudgetContextComposer, estimate_tokens
from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    CapabilityContext,
    ColumnProfile,
    ColumnSchema,
    ComposedContext,
    FreshnessReport,
    GovernanceContext,
    GrainStatement,
    GranularityContext,
    JoinEdge,
    OntologyConcept,
    OntologyContext,
    ProfileContext,
    ProvenanceSource,
    QualityReport,
    QualityState,
    RetrievedContext,
    RuntimeContext,
    SchemaContext,
    SkillRef,
    TableSchema,
    TaxonomyContext,
    TaxonomyNode,
    TopologyContext,
    TrustLevel,
    ValidationStatus,
)
from datahek.kernel.context import RequestContext


def _envelope(kind, provenance=ProvenanceSource.DATABASE,
              validation=ValidationStatus.NOT_REQUIRED, trust=TrustLevel.STRUCTURAL):
    return ArtifactEnvelope(kind=kind, schema_version=1, provenance=provenance, trust=trust,
                            validation=validation, confidence=1.0,
                            generated_at="2026-09-21T00:00:00Z")


def _schema():
    def table(name, *columns):
        return TableSchema(name=name, columns=tuple(
            ColumnSchema(name=column, data_type="text", nullable=True, ordinal=index)
            for index, column in enumerate(columns)), primary_key=("id",))

    return SchemaContext(
        envelope=_envelope(ArtifactKind.SCHEMA), database="d", schema="public",
        tables=(table("orders", "id", "customer_id", "amount"),
                table("customers", "id", "name")), schema_hash="h1")


def _profiles():
    return ProfileContext(
        envelope=_envelope(ArtifactKind.PROFILE),
        tables={"orders": (
            ColumnProfile(name="id", row_count=100, null_ratio=0.0,
                          role_candidates=("identifier",)),
            ColumnProfile(name="amount", row_count=100, null_ratio=0.0,
                          role_candidates=("measure",))),
            "customers": (
                ColumnProfile(name="name", row_count=50, null_ratio=0.0,
                              role_candidates=("dimension",)),
                ColumnProfile(name="created_at", row_count=50, null_ratio=0.0,
                              role_candidates=("temporal",)))})


def _topology():
    return TopologyContext(
        envelope=_envelope(ArtifactKind.TOPOLOGY),
        edges=(JoinEdge(left="orders.customer_id", right="customers.id", kind="fk",
                        cardinality="N:1", fanout_risk="low",
                        provenance=ProvenanceSource.DATABASE, confidence=1.0),))


def _granularity():
    return GranularityContext(
        envelope=_envelope(ArtifactKind.GRANULARITY),
        grains=(GrainStatement(table="orders", statement="1 row of orders = 1 Order",
                               source=ProvenanceSource.SYSTEM,
                               validation=ValidationStatus.PENDING, confidence=0.9),
                GrainStatement(table="customers", statement="1 row of customers = 1 Customer",
                               source=ProvenanceSource.SYSTEM,
                               validation=ValidationStatus.PENDING, confidence=0.9)),
        metric_grains=())


def _taxonomy():
    return TaxonomyContext(
        envelope=_envelope(ArtifactKind.TAXONOMY, ProvenanceSource.SYSTEM,
                           ValidationStatus.PENDING),
        nodes=(TaxonomyNode(path=("D", "orders", "Identifier"), members=("orders.id",),
                            node_kind="category", provenance=ProvenanceSource.SYSTEM,
                            validation=ValidationStatus.PENDING, confidence=0.9),
               TaxonomyNode(path=("D", "customers", "Dimension"), members=("customers.name",),
                            node_kind="category", provenance=ProvenanceSource.SYSTEM,
                            validation=ValidationStatus.PENDING, confidence=0.8)))


def _ontology():
    return OntologyContext(
        envelope=_envelope(ArtifactKind.ONTOLOGY, ProvenanceSource.LLM,
                           ValidationStatus.PENDING, TrustLevel.PROPOSED),
        concepts=(OntologyConcept(name="Order", kind="entity", maps_to=("orders",),
                                  attributes=(), provenance=ProvenanceSource.LLM,
                                  validation=ValidationStatus.PENDING, confidence=0.6),),
        relationships=())


def _governance():
    return GovernanceContext(
        envelope=_envelope(ArtifactKind.GOVERNANCE, ProvenanceSource.SYSTEM,
                           ValidationStatus.NOT_REQUIRED, TrustLevel.SYSTEM),
        sensitive_columns=(), restricted_columns=(), allowed_operations=("SELECT",),
        masking_policy_refs=(), permission_version="p1")


def _quality(state=QualityState.SUFFICIENT):
    return QualityReport(state=state, schema_completeness=1.0, profiling_coverage=1.0,
                         semantic_confidence=0.6, relationship_coverage=0.9,
                         granularity_confidence=0.9, human_validation=0.0,
                         freshness_score=1.0, governance_coverage=1.0)


def _freshness():
    return FreshnessReport(state="fresh", age_seconds=0, schema_hash_matches=True,
                           permission_version_matches=True)


def _retrieved(*, taxonomy=True, ontology=True):
    return RetrievedContext(
        context_id="ctx1", version=3, schema_hash="h1", scope="connection",
        connection_id="conn1", schema=_schema().tables, profiles=_profiles().tables,
        topology=_topology(), granularity=_granularity(),
        taxonomy=_taxonomy() if taxonomy else None,
        ontology=_ontology() if ontology else None,
        governance=_governance(),
        metrics=({"name": "revenue", "table": "orders",
                  "description": "total sales"},),
        quality=_quality(), freshness=_freshness())


class TestComposer(unittest.TestCase):
    def setUp(self):
        self.composer = BudgetContextComposer()
        self.ctx = RequestContext(source="cli")

    def compose(self, retrieved, budget, question="revenue by customer"):
        return asyncio.run(self.composer.compose(
            self.ctx, retrieved, RuntimeContext(question=question),
            budget_tokens=budget))

    def test_large_budget_keeps_everything(self):
        composed = self.compose(_retrieved(), 100_000)
        self.assertEqual(composed.dropped, ())
        self.assertEqual(composed.insufficient_reason, "")
        self.assertGreater(composed.tokens_estimate, 0)
        self.assertIsNotNone(composed.taxonomy)
        self.assertIsNotNone(composed.ontology)
        self.assertEqual(len(composed.metrics), 1)

    def test_over_budget_drops_in_documented_order(self):
        retrieved = _retrieved()
        mandatory = (estimate_tokens(retrieved.schema)
                     + estimate_tokens(retrieved.governance)
                     + estimate_tokens(retrieved.granularity))
        budget = mandatory + estimate_tokens(retrieved.profiles) + 1
        composed = self.compose(retrieved, budget)
        self.assertEqual(composed.dropped,
                         ("taxonomy", "topology", "ontology", "metrics"))
        self.assertIsNotNone(composed.governance)
        self.assertIsNotNone(composed.granularity)
        self.assertEqual(composed.profiles, dict(retrieved.profiles))
        self.assertLessEqual(composed.tokens_estimate, budget)

    def test_impossible_budget_marks_insufficient(self):
        composed = self.compose(_retrieved(), 1)
        self.assertEqual(composed.insufficient_reason, "budget")
        self.assertEqual(composed.dropped, ())

    def test_composition_is_deterministic(self):
        first = self.compose(_retrieved(), 100_000)
        second = self.compose(_retrieved(), 100_000)
        self.assertEqual(first, second)


class TestCompiler(unittest.TestCase):
    def setUp(self):
        self.compiler = PackageContextCompiler()
        self.ctx = RequestContext(source="cli")

    def compile_package(self, composed, **kwargs):
        return asyncio.run(self.compiler.compile(
            self.ctx, composed, quality=_quality(), freshness=_freshness(), **kwargs))

    def _composed(self, budget=100_000, **kwargs):
        return asyncio.run(BudgetContextComposer().compose(
            self.ctx, _retrieved(**kwargs), RuntimeContext(question="revenue"),
            budget_tokens=budget))

    def test_semantics_summary_from_taxonomy(self):
        package = self.compile_package(self._composed())
        self.assertEqual(package.semantics.identifiers, ("orders.id",))
        self.assertEqual(package.semantics.dimensions, ("customers.name",))
        self.assertEqual([m["name"] for m in package.semantics.metrics], ["revenue"])

    def test_semantics_fallback_to_profile_roles(self):
        package = self.compile_package(self._composed(taxonomy=False))
        self.assertIn("orders.id", package.semantics.identifiers)
        self.assertIn("customers.name", package.semantics.dimensions)
        self.assertIn("customers.created_at", package.semantics.temporal_fields)

    def test_trust_floor_from_included_content(self):
        with_ontology = self.compile_package(self._composed())
        self.assertEqual(with_ontology.trust, TrustLevel.PROPOSED)
        without = self.compile_package(self._composed(ontology=False))
        self.assertEqual(without.trust, TrustLevel.STRUCTURAL)

    def test_budget_drops_become_degraded(self):
        retrieved = _retrieved()
        mandatory = (estimate_tokens(retrieved.schema)
                     + estimate_tokens(retrieved.governance)
                     + estimate_tokens(retrieved.granularity))
        composed = self._composed(budget=mandatory + 1)
        package = self.compile_package(composed)
        self.assertEqual(package.degraded, composed.dropped)
        self.assertEqual(package.budget.dropped_sections, composed.dropped)
        self.assertEqual(package.budget.tokens_estimate, composed.tokens_estimate)

    def test_insufficient_composition_overrides_quality(self):
        package = self.compile_package(self._composed(budget=1))
        self.assertEqual(package.quality.state, QualityState.INSUFFICIENT)
        self.assertEqual(package.quality.details.get("insufficient_reason"), "budget")

    def test_capability_passthrough(self):
        package = self.compile_package(
            self._composed(), skills=(SkillRef(name="sql.basic", version="1"),),
            tools=(), providers=("postgres",))
        self.assertEqual(package.capabilities.skills[0].name, "sql.basic")
        self.assertEqual(package.capabilities.providers, ("postgres",))
        self.assertEqual(package.governance.permission_version, "p1")

    def test_compilation_is_deterministic(self):
        composed = self._composed()
        first = self.compile_package(composed)
        second = self.compile_package(composed)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
