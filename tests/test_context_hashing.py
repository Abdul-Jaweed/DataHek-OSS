"""Canonical schema hashing — deterministic change detection (ADR-010)."""
import unittest

from datahek.contracts.context import ColumnSchema, TableSchema
from datahek.context.hashing import canonical_schema_form, schema_hash


def _tables():
    return [
        TableSchema(
            name="orders",
            columns=(
                ColumnSchema(name="order_id", data_type="uuid", nullable=False,
                             ordinal=1, is_primary_key=True),
                ColumnSchema(name="amount", data_type="numeric", nullable=True,
                             ordinal=2),
            ),
            primary_key=("order_id",),
            foreign_keys=(("customer_id", "customers.id"),),
            indexes=("idx_orders_created",),
            estimated_rows=100,
        ),
        TableSchema(name="customers", columns=(
            ColumnSchema(name="id", data_type="uuid", nullable=False, ordinal=1,
                         is_primary_key=True),)),
    ]


class TestSchemaHashing(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(schema_hash(_tables()), schema_hash(_tables()))

    def test_table_order_does_not_matter(self):
        tables = _tables()
        self.assertEqual(schema_hash(tables), schema_hash(list(reversed(tables))))

    def test_column_type_change_detected(self):
        tables = _tables()
        changed = [TableSchema(
            name="orders",
            columns=(
                ColumnSchema(name="order_id", data_type="uuid", nullable=False, ordinal=1),
                ColumnSchema(name="amount", data_type="text", nullable=True, ordinal=2),
            ),
        )]
        self.assertNotEqual(schema_hash(tables), schema_hash(changed))

    def test_nullability_change_detected(self):
        tables = _tables()
        changed = [TableSchema(name="orders", columns=(
            ColumnSchema(name="order_id", data_type="uuid", nullable=True, ordinal=1),))]
        self.assertNotEqual(schema_hash(tables), schema_hash(changed))

    def test_primary_key_change_detected(self):
        tables = _tables()
        changed = [TableSchema(name="orders", columns=tables[0].columns,
                               primary_key=("amount",))]
        self.assertNotEqual(schema_hash(tables), schema_hash(changed))

    def test_comments_and_estimates_ignored(self):
        tables = _tables()
        noisy = [
            TableSchema(name="orders", columns=tables[0].columns,
                        primary_key=tables[0].primary_key,
                        foreign_keys=tables[0].foreign_keys,
                        indexes=tables[0].indexes,
                        comment="do not hash me", estimated_rows=999999),
            tables[1],
        ]
        self.assertEqual(schema_hash(tables), schema_hash(noisy))

    def test_canonical_form_is_stable_text(self):
        form = canonical_schema_form(_tables())
        self.assertIn('"orders"', form)
        self.assertIn('"amount"', form)
        self.assertEqual(len(schema_hash(_tables())), 64)


if __name__ == "__main__":
    unittest.main()
