"""TopologyService — FK edges, inferred joins, bounded join paths."""
import unittest

from datahek.contracts.context import ArtifactKind, ProvenanceSource, SchemaContext
from datahek.context.snapshot import build_schema_context
from datahek.context.topology import build_topology_context, infer_join_edges
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta


def _schema():
    catalog = SchemaCatalog(source="c1:appdb", tables=[
        TableMeta(
            name="customers",
            columns=[ColumnMeta(name="id", data_type="integer", nullable=False, ordinal=0,
                                is_primary_key=True),
                     ColumnMeta(name="name", data_type="text", ordinal=1)],
            primary_key=("id",),
        ),
        TableMeta(
            name="orders",
            columns=[ColumnMeta(name="id", data_type="integer", nullable=False, ordinal=0,
                                is_primary_key=True),
                     ColumnMeta(name="customer_id", data_type="integer", nullable=False, ordinal=1,
                                is_foreign_key=True, references="customers.id"),
                     ColumnMeta(name="region_id", data_type="integer", ordinal=2)],
            primary_key=("id",),
            foreign_keys=(("customer_id", "customers.id"),),
        ),
        TableMeta(
            name="regions",
            columns=[ColumnMeta(name="id", data_type="integer", nullable=False, ordinal=0,
                                is_primary_key=True)],
            primary_key=("id",),
        ),
    ])
    return build_schema_context(catalog, database="appdb")


class TestInferJoinEdges(unittest.TestCase):
    def test_infers_id_column_to_target_pk(self):
        edges = infer_join_edges(_schema())
        self.assertEqual(len(edges), 1)
        edge = edges[0]
        self.assertEqual(edge.left, "orders.region_id")
        self.assertEqual(edge.right, "regions.id")
        self.assertEqual(edge.kind, "inferred")
        self.assertEqual(edge.cardinality, "N:1")
        self.assertEqual(edge.fanout_risk, "low")
        self.assertEqual(edge.provenance, ProvenanceSource.INFERRED)
        self.assertGreaterEqual(edge.confidence, 0.6)

    def test_does_not_duplicate_fk_edges(self):
        edges = infer_join_edges(_schema())
        self.assertFalse(any(e.left == "orders.customer_id" for e in edges))

    def test_skips_missing_target_table(self):
        catalog = SchemaCatalog(source="c1", tables=[
            TableMeta(name="orders", columns=[
                ColumnMeta(name="widget_id", data_type="integer", ordinal=0)]),
        ])
        schema = build_schema_context(catalog, database="appdb")
        self.assertEqual(infer_join_edges(schema), ())


class TestTopologyContext(unittest.TestCase):
    def test_builds_edges_and_paths(self):
        context = build_topology_context(_schema())
        self.assertEqual(context.envelope.kind, ArtifactKind.TOPOLOGY)
        kinds = {e.kind for e in context.edges}
        self.assertEqual(kinds, {"fk", "inferred"})
        fk = next(e for e in context.edges if e.kind == "fk")
        self.assertEqual(fk.left, "orders.customer_id")
        self.assertEqual(fk.right, "customers.id")
        self.assertEqual(fk.provenance, ProvenanceSource.DATABASE)
        self.assertEqual(fk.confidence, 1.0)
        direct = context.join_paths.get("orders->customers")
        self.assertIsNotNone(direct)
        self.assertIn(("orders.customer_id=customers.id",), direct)
        two_hop = context.join_paths.get("regions->customers")
        self.assertIn(
            ("orders.region_id=regions.id", "orders.customer_id=customers.id"), two_hop)

    def test_path_depth_is_bounded(self):
        context = build_topology_context(_schema(), max_depth=1)
        self.assertNotIn("regions->customers", context.join_paths)


if __name__ == "__main__":
    unittest.main()
