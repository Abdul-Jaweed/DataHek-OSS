"""SchemaContext snapshots — canonical artifacts built from discovered catalogs."""
import unittest

from datahek.context.hashing import schema_hash
from datahek.context.snapshot import build_schema_context
from datahek.contracts.context import ArtifactKind, ProvenanceSource, TrustLevel
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta


def _catalog():
    return SchemaCatalog(source="c1:appdb", tables=[
        TableMeta(
            name="orders",
            columns=[
                ColumnMeta(name="id", data_type="integer", nullable=False, ordinal=0,
                           is_primary_key=True),
                ColumnMeta(name="customer_id", data_type="integer", nullable=False, ordinal=1,
                           is_foreign_key=True, references="customers.id", default=None),
                ColumnMeta(name="amount", data_type="numeric", ordinal=2, description="order value"),
            ],
            row_count=100,
            primary_key=("id",),
            foreign_keys=(("customer_id", "customers.id"),),
            indexes=("idx_orders_amount",),
        ),
    ])


class TestSnapshot(unittest.TestCase):
    def test_builds_schema_context(self):
        ctx = build_schema_context(_catalog(), database="appdb")
        self.assertEqual(ctx.envelope.kind, ArtifactKind.SCHEMA)
        self.assertEqual(ctx.envelope.provenance, ProvenanceSource.DATABASE)
        self.assertEqual(ctx.envelope.trust, TrustLevel.STRUCTURAL)
        self.assertEqual(ctx.envelope.confidence, 1.0)
        self.assertEqual(ctx.database, "appdb")
        self.assertEqual(ctx.schema, "public")
        self.assertEqual(len(ctx.tables), 1)
        table = ctx.tables[0]
        self.assertEqual(table.name, "orders")
        self.assertEqual(table.primary_key, ("id",))
        self.assertEqual(table.foreign_keys, (("customer_id", "customers.id"),))
        self.assertEqual(table.indexes, ("idx_orders_amount",))
        self.assertEqual(table.estimated_rows, 100)
        columns = {c.name: c for c in table.columns}
        self.assertTrue(columns["id"].is_primary_key)
        self.assertTrue(columns["customer_id"].is_foreign_key)
        self.assertEqual(columns["customer_id"].references, "customers.id")
        self.assertEqual(columns["amount"].comment, "order value")

    def test_hash_matches_canonical_hashing(self):
        ctx = build_schema_context(_catalog(), database="appdb")
        self.assertEqual(ctx.schema_hash, schema_hash(ctx.tables))
        self.assertEqual(len(ctx.schema_hash), 64)

    def test_generated_at_is_overridable(self):
        ctx = build_schema_context(_catalog(), database="appdb",
                                   generated_at="2026-09-21T00:00:00Z")
        self.assertEqual(ctx.envelope.generated_at, "2026-09-21T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
