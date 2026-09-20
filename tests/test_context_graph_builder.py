"""SchemaGraphBuilder — artifact projection with idempotent rebuilds and pruning."""
import asyncio
import unittest

from datahek.context.graph.builder import SchemaGraphBuilder
from datahek.context.graph.memory import InMemoryGraphRepository
from datahek.context.snapshot import build_schema_context
from datahek.context.topology import build_topology_context
from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    ColumnProfile,
    GrainStatement,
    GranularityContext,
    ProfileContext,
    ProvenanceSource,
    TrustLevel,
    ValidationStatus,
)
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext


def _envelope(kind):
    return ArtifactEnvelope(kind=kind, schema_version=1,
                            provenance=ProvenanceSource.DATABASE,
                            trust=TrustLevel.STRUCTURAL,
                            validation=ValidationStatus.NOT_REQUIRED,
                            confidence=1.0, generated_at="2026-09-21T00:00:00Z")


def _schema(names=("orders", "customers")):
    tables = []
    if "orders" in names:
        tables.append(TableMeta(name="orders", columns=[
            ColumnMeta(name="id", data_type="integer", nullable=False, ordinal=0,
                       is_primary_key=True),
            ColumnMeta(name="customer_id", data_type="integer", nullable=False, ordinal=1,
                       is_foreign_key=True, references="customers.id"),
            ColumnMeta(name="amount", data_type="numeric", ordinal=2)],
            primary_key=("id",), foreign_keys=(("customer_id", "customers.id"),),
            row_count=100))
    if "customers" in names:
        tables.append(TableMeta(name="customers", columns=[
            ColumnMeta(name="id", data_type="integer", nullable=False, ordinal=0,
                       is_primary_key=True)], primary_key=("id",), row_count=50))
    return build_schema_context(SchemaCatalog(source="c1:appdb", tables=tables),
                                database="appdb")


def _profiles():
    orders = (ColumnProfile(name="id", row_count=100, null_ratio=0.0, distinct_count=100,
                            uniqueness_ratio=1.0, role_candidates=("identifier",),
                            role_confidence={"identifier": 1.0}),
              ColumnProfile(name="amount", row_count=100, null_ratio=0.0,
                            distinct_count=80, uniqueness_ratio=0.8,
                            role_candidates=("measure",), role_confidence={"measure": 0.9}))
    return ProfileContext(envelope=_envelope(ArtifactKind.PROFILE), tables={"orders": orders})


def _granularity():
    return GranularityContext(
        envelope=_envelope(ArtifactKind.GRANULARITY),
        grains=(GrainStatement(table="orders", statement="1 row of orders = 1 Order",
                               entity="Order", source=ProvenanceSource.SYSTEM,
                               validation=ValidationStatus.PENDING, confidence=0.9),),
        metric_grains=())


class _Down(InMemoryGraphRepository):
    async def health_check(self):
        return False


class TestGraphBuilder(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryGraphRepository()
        self.builder = SchemaGraphBuilder(self.repo)
        self.ctx = RequestContext(source="cli")
        self.schema = _schema()

    def build(self, **kwargs):
        return asyncio.run(self.builder.build(
            self.ctx, "conn-1", schema=kwargs.pop("schema", self.schema),
            profiles=kwargs.pop("profiles", None),
            topology=kwargs.pop("topology", None),
            granularity=kwargs.pop("granularity", None),
            metrics=kwargs.pop("metrics", ()), **kwargs))

    def labels(self, label):
        return asyncio.run(self.repo.find_nodes(self.ctx, label=label, limit=100))

    def test_projects_schema_nodes_and_edges(self):
        report = self.build()
        self.assertFalse(report.degraded)
        self.assertEqual(report.nodes_written, 7)
        tables = self.labels("Table")
        self.assertEqual({t.id for t in tables},
                         {"table:conn-1:orders", "table:conn-1:customers"})
        columns = self.labels("Column")
        self.assertEqual(len(columns), 4)
        neighbors = asyncio.run(self.repo.neighbors(self.ctx, "table:conn-1:orders"))
        labels = {n.label for n in neighbors}
        self.assertEqual(labels, {"Column", "Connection"})

    def test_topology_edges_become_references_and_joins(self):
        topology = build_topology_context(self.schema)
        self.build(topology=topology)
        neighbors = asyncio.run(self.repo.neighbors(
            self.ctx, "column:conn-1:orders.customer_id", rel_type="REFERENCES"))
        self.assertEqual([n.id for n in neighbors], ["column:conn-1:customers.id"])

    def test_profile_and_grain_become_properties(self):
        self.build(profiles=_profiles(), granularity=_granularity())
        orders = asyncio.run(self.repo.get_node(self.ctx, "table:conn-1:orders"))
        self.assertEqual(orders.properties["grain"], "1 row of orders = 1 Order")
        self.assertEqual(orders.properties["row_count"], "100")
        amount = asyncio.run(self.repo.get_node(self.ctx, "column:conn-1:orders.amount"))
        self.assertEqual(amount.properties["roles"], "measure")
        identifier = asyncio.run(self.repo.get_node(self.ctx, "column:conn-1:orders.id"))
        self.assertEqual(identifier.properties["roles"], "identifier")

    def test_metrics_become_nodes(self):
        self.build(metrics=[{"name": "revenue", "table": "orders", "aggregate": "sum",
                             "column": "amount"}])
        metrics = self.labels("Metric")
        self.assertEqual([m.id for m in metrics], ["metric:conn-1:revenue"])
        neighbors = asyncio.run(self.repo.neighbors(self.ctx, "table:conn-1:orders",
                                                    rel_type="HAS_METRIC"))
        self.assertEqual([n.id for n in neighbors], ["metric:conn-1:revenue"])

    def test_rebuild_is_idempotent_and_prunes(self):
        first = self.build()
        second = self.build()
        self.assertEqual(second.nodes_written, first.nodes_written)
        self.assertEqual(second.nodes_pruned, 0)
        self.assertEqual(len(self.labels("Table")), 2)
        shrunk = _schema(names=("customers",))
        report = self.build(schema=shrunk)
        self.assertEqual(report.nodes_pruned, 4)
        self.assertEqual([t.id for t in self.labels("Table")], ["table:conn-1:customers"])
        self.assertIsNone(asyncio.run(
            self.repo.get_node(self.ctx, "column:conn-1:orders.amount")))

    def test_tenant_stamped(self):
        self.build()
        table = asyncio.run(self.repo.get_node(self.ctx, "table:conn-1:orders"))
        self.assertEqual(table.org_id, "default")
        self.assertEqual(table.properties["connection_id"], "conn-1")

    def test_degraded_when_graph_unavailable(self):
        builder = SchemaGraphBuilder(_Down())
        report = asyncio.run(builder.build(self.ctx, "conn-1", schema=self.schema))
        self.assertTrue(report.degraded)
        self.assertEqual(report.nodes_written, 0)
        self.assertIn("unavailable", report.warnings[0])
        self.assertEqual(asyncio.run(_Down().find_nodes(self.ctx, label="Table")), [])


if __name__ == "__main__":
    unittest.main()
