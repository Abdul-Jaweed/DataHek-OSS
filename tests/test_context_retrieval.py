"""ContextRetriever — deterministic relevance selection from the active record."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from datahek.context.registry import ContextRegistryService
from datahek.context.retriever import ContextRetrieverService, question_tokens
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
    LifecycleState,
    OntologyConcept,
    OntologyContext,
    ProfileContext,
    ProvenanceSource,
    QualityReport,
    QualityState,
    SchemaContext,
    TableSchema,
    TaxonomyContext,
    TaxonomyNode,
    TopologyContext,
    TrustLevel,
    ValidationStatus,
)
from datahek.defaults.context_store import SqliteContextRegistry, SqliteContextStore
from datahek.kernel.context import RequestContext


def _envelope(kind, provenance=ProvenanceSource.DATABASE,
              validation=ValidationStatus.NOT_REQUIRED, trust=TrustLevel.STRUCTURAL):
    return ArtifactEnvelope(kind=kind, schema_version=1, provenance=provenance, trust=trust,
                            validation=validation, confidence=1.0,
                            generated_at="2026-09-21T00:00:00Z")


def _schema():
    def table(name, *columns, pk=("id",)):
        return TableSchema(name=name, columns=tuple(
            ColumnSchema(name=column, data_type="text", nullable=True, ordinal=index)
            for index, column in enumerate(columns)), primary_key=pk)

    return SchemaContext(
        envelope=_envelope(ArtifactKind.SCHEMA), database="d", schema="public",
        tables=(table("orders", "id", "customer_id", "amount", "created_at"),
                table("customers", "id", "name"),
                table("products", "id", "title", "price")),
        schema_hash="h1")


def _profiles():
    def column(name):
        return ColumnProfile(name=name, row_count=100, null_ratio=0.0)

    return ProfileContext(
        envelope=_envelope(ArtifactKind.PROFILE),
        tables={"orders": (column("id"), column("amount")),
                "customers": (column("id"),),
                "products": (column("id"),)})


def _topology():
    return TopologyContext(
        envelope=_envelope(ArtifactKind.TOPOLOGY),
        edges=(JoinEdge(left="orders.customer_id", right="customers.id", kind="fk",
                        cardinality="N:1", fanout_risk="low",
                        provenance=ProvenanceSource.DATABASE, confidence=1.0),
               JoinEdge(left="orders.product_id", right="products.id", kind="inferred",
                        cardinality="N:1", fanout_risk="low",
                        provenance=ProvenanceSource.INFERRED, confidence=0.6)),
        join_paths={"orders->customers": (("orders.customer_id=customers.id",),),
                    "orders->products": (("orders.product_id=products.id",),)})


def _granularity():
    return GranularityContext(
        envelope=_envelope(ArtifactKind.GRANULARITY),
        grains=tuple(GrainStatement(table=name, statement=f"1 row of {name} = 1 X",
                                    source=ProvenanceSource.SYSTEM,
                                    validation=ValidationStatus.PENDING, confidence=0.9)
                     for name in ("orders", "customers", "products")),
        metric_grains=())


def _taxonomy():
    return TaxonomyContext(
        envelope=_envelope(ArtifactKind.TAXONOMY),
        nodes=tuple(TaxonomyNode(path=("D", name, "Identifier"), members=(f"{name}.id",),
                                 node_kind="category", provenance=ProvenanceSource.SYSTEM,
                                 validation=ValidationStatus.PENDING, confidence=0.9)
                    for name in ("orders", "customers", "products")))


def _ontology():
    return OntologyContext(
        envelope=_envelope(ArtifactKind.ONTOLOGY, ProvenanceSource.LLM,
                           ValidationStatus.PENDING, TrustLevel.PROPOSED),
        concepts=(
            OntologyConcept(name="Customer", kind="entity", maps_to=("customers",),
                            attributes=(), provenance=ProvenanceSource.LLM,
                            validation=ValidationStatus.PENDING, confidence=0.6,
                            description="a buyer", synonyms=("client",)),
            OntologyConcept(name="Catalogue", kind="entity", maps_to=("products",),
                            attributes=(), provenance=ProvenanceSource.LLM,
                            validation=ValidationStatus.PENDING, confidence=0.6),
        ),
        relationships=(),
    )


def _governance():
    return GovernanceContext(
        envelope=_envelope(ArtifactKind.GOVERNANCE, ProvenanceSource.SYSTEM,
                           ValidationStatus.NOT_REQUIRED, TrustLevel.SYSTEM),
        sensitive_columns=("customers.name",), restricted_columns=(),
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


class _FakeSemanticStore:
    async def list(self, ctx):
        return [{"name": "revenue", "table": "orders", "aggregate": "sum",
                 "column": "amount", "description": "total sales value"}]


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        path = str(Path(self._tmp.name) / "ctx.db")
        self.registry = SqliteContextRegistry(path)
        self.store = SqliteContextStore(path)
        self.registry_service = ContextRegistryService(self.registry, self.store)
        self.retriever = ContextRetrieverService(self.registry, self.store,
                                                 semantic_store=_FakeSemanticStore())
        self.ctx = RequestContext(source="cli")
        self.call(self.registry_service.publish(
            self.ctx, connection_id="conn1", scope="connection", schema_hash="h1",
            artifacts={
                ArtifactKind.SCHEMA: _schema(),
                ArtifactKind.PROFILE: _profiles(),
                ArtifactKind.TOPOLOGY: _topology(),
                ArtifactKind.GRANULARITY: _granularity(),
                ArtifactKind.TAXONOMY: _taxonomy(),
                ArtifactKind.ONTOLOGY: _ontology(),
                ArtifactKind.GOVERNANCE: _governance(),
            },
            quality=_quality(), freshness=_freshness()))

    def tearDown(self):
        self._tmp.cleanup()

    def call(self, coro):
        return asyncio.run(coro)

    def retrieve(self, question, **kwargs):
        return self.call(self.retriever.retrieve(self.ctx, connection_id="conn1",
                                                 question=question, **kwargs))


class TestRetrieval(_Base):
    def test_metric_name_selects_orders(self):
        retrieved = self.retrieve("what was revenue by customer?")
        names = {table.name for table in retrieved.schema}
        self.assertIn("orders", names)
        self.assertIn("customers", names)
        self.assertNotIn("products", names)
        metric_names = {str(m.get("name")) for m in retrieved.metrics}
        self.assertEqual(metric_names, {"revenue"})

    def test_column_name_selects_products(self):
        retrieved = self.retrieve("what is the average price of the products?")
        names = {table.name for table in retrieved.schema}
        self.assertIn("products", names)
        self.assertNotIn("customers", names)

    def test_join_edges_only_between_selected_tables(self):
        retrieved = self.retrieve("revenue by customer")
        edges = {(edge.left, edge.right) for edge in retrieved.topology.edges}
        self.assertIn(("orders.customer_id", "customers.id"), edges)
        self.assertNotIn(("orders.product_id", "products.id"), edges)
        self.assertNotIn("orders->products", retrieved.topology.join_paths)

    def test_slices_track_selected_tables(self):
        retrieved = self.retrieve("products price")
        self.assertEqual([grain.table for grain in retrieved.granularity.grains], ["products"])
        self.assertEqual({node.path[1] for node in retrieved.taxonomy.nodes}, {"products"})
        self.assertEqual([c.name for c in retrieved.ontology.concepts], ["Catalogue"])
        self.assertEqual(set(retrieved.profiles), {"products"})

    def test_governance_always_retrieved(self):
        retrieved = self.retrieve("products price")
        self.assertIsNotNone(retrieved.governance)
        self.assertEqual(retrieved.governance.sensitive_columns, ("customers.name",))

    def test_missing_record_returns_none(self):
        self.assertIsNone(self.call(self.retriever.retrieve(
            self.ctx, connection_id="missing", question="anything")))

    def test_stale_when_schema_hash_differs(self):
        fresh = self.retrieve("orders")
        self.assertFalse(fresh.stale)
        stale = self.retrieve("orders", current_schema_hash="different")
        self.assertTrue(stale.stale)

    def test_fallback_selects_tables_when_no_match(self):
        retrieved = self.retrieve("zzz nothing matches")
        self.assertGreaterEqual(len(retrieved.schema), 1)
        self.assertLessEqual(len(retrieved.schema), 8)


class TestTokens(unittest.TestCase):
    def test_stopwords_removed(self):
        tokens = question_tokens("How many orders were there?")
        self.assertIn("orders", tokens)
        self.assertNotIn("how", tokens)


if __name__ == "__main__":
    unittest.main()
