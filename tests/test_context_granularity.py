"""GranularityService — table and metric grain statements from structural facts."""
import unittest

from datahek.context.granularity import build_granularity_context, singularize
from datahek.context.snapshot import build_schema_context
from datahek.contracts.context import ArtifactKind, ColumnProfile, ProfileContext, ProvenanceSource
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta


def _schema():
    catalog = SchemaCatalog(source="c1:appdb", tables=[
        TableMeta(name="orders", columns=[
            ColumnMeta(name="id", data_type="integer", nullable=False, ordinal=0,
                       is_primary_key=True),
            ColumnMeta(name="amount", data_type="numeric", ordinal=1)],
            primary_key=("id",)),
        TableMeta(name="order_items", columns=[
            ColumnMeta(name="order_id", data_type="integer", nullable=False, ordinal=0),
            ColumnMeta(name="sku", data_type="text", ordinal=1)],
            primary_key=("order_id", "sku")),
        TableMeta(name="events", columns=[
            ColumnMeta(name="payload", data_type="text", ordinal=0)]),
    ])
    return build_schema_context(catalog, database="appdb")


def _profiles():
    envelope = build_granularity_context(_schema()).envelope
    orders = (ColumnProfile(name="id", row_count=100, null_ratio=0.0, distinct_count=100,
                            uniqueness_ratio=1.0, role_candidates=("identifier",),
                            role_confidence={"identifier": 1.0}),)
    return ProfileContext(envelope=envelope, tables={"orders": orders})


class TestSingularize(unittest.TestCase):
    def test_plural_forms(self):
        self.assertEqual(singularize("orders"), "order")
        self.assertEqual(singularize("order_items"), "order_item")
        self.assertEqual(singularize("categories"), "category")
        self.assertEqual(singularize("business"), "business")
        self.assertEqual(singularize("events"), "event")


class TestGranularity(unittest.TestCase):
    def test_single_pk_with_identifier_profile(self):
        context = build_granularity_context(_schema(), _profiles())
        self.assertEqual(context.envelope.kind, ArtifactKind.GRANULARITY)
        orders = next(g for g in context.grains if g.table == "orders")
        self.assertEqual(orders.statement, "1 row of orders = 1 Order")
        self.assertEqual(orders.entity, "Order")
        self.assertEqual(orders.source, ProvenanceSource.SYSTEM)
        self.assertAlmostEqual(orders.confidence, 0.9)

    def test_composite_pk(self):
        context = build_granularity_context(_schema())
        items = next(g for g in context.grains if g.table == "order_items")
        self.assertIn("identified by", items.statement)
        self.assertIn("order_id", items.statement)
        self.assertAlmostEqual(items.confidence, 0.8)

    def test_no_pk_is_unverified(self):
        context = build_granularity_context(_schema())
        events = next(g for g in context.grains if g.table == "events")
        self.assertIn("unconfirmed", events.statement)
        self.assertLess(events.confidence, 0.5)
        self.assertIn("primary key", events.qualifier)

    def test_metric_grain_from_metrics(self):
        context = build_granularity_context(
            _schema(), _profiles(),
            metrics=[{"name": "revenue", "table": "orders"},
                     {"name": "orphan_metric", "table": "missing"}])
        revenue = next(m for m in context.metric_grains if m.metric == "revenue")
        self.assertEqual(revenue.valid_at, ("1 row of orders = 1 Order",))
        self.assertIsNone(revenue.caveat)
        orphan = next(m for m in context.metric_grains if m.metric == "orphan_metric")
        self.assertEqual(orphan.valid_at, ("unknown",))
        self.assertIn("missing", orphan.caveat)

    def test_metric_grain_caveat_for_unverified_table(self):
        context = build_granularity_context(
            _schema(), metrics=[{"name": "event_count", "table": "events"}])
        grain = next(m for m in context.metric_grains if m.metric == "event_count")
        self.assertIn("unverified", grain.caveat)


if __name__ == "__main__":
    unittest.main()
