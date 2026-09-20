"""SchemaProfiler — deterministic, privacy-aware statistics via the guarded engine."""
import asyncio
import unittest

from datahek.contracts.connections import Connection
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind, ReadOnlyLevel
from datahek.context.profiler import SchemaProfiler, looks_sensitive
from datahek.engine.executor import Engine, ProviderRegistry
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext

_CATALOG = SchemaCatalog(source="c1:appdb", tables=[
    TableMeta(name="orders", columns=[
        ColumnMeta(name="order_id", data_type="uuid", nullable=False, ordinal=0,
                   is_primary_key=True),
        ColumnMeta(name="amount", data_type="double precision", nullable=True, ordinal=1),
        ColumnMeta(name="status", data_type="text", nullable=True, ordinal=2),
        ColumnMeta(name="created_at", data_type="timestamp with time zone", ordinal=3),
        ColumnMeta(name="card_number", data_type="text", ordinal=4),
    ]),
])

plan_table_columns = [column.name for column in _CATALOG.tables[0].columns]


class _ProfileProvider:
    provider_id = "fake"
    capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, dialect="fake",
                                         read_only=ReadOnlyLevel.STRUCTURAL,
                                         max_result_rows=1000)
    DISTINCT = {"order_id": 100, "amount": 80, "status": 4, "created_at": 90,
                "card_number": 95}

    async def connect(self, connection):
        return object()

    async def compile_and_execute(self, client, plan, ctx):
        aggregates = plan.nodes[0].aggregates
        values = {"n": 100}
        for agg in aggregates:
            if agg.alias == "n":
                continue
            index = int(agg.alias.split("_")[1])
            column = plan_table_columns[index]
            if agg.alias.startswith("nn_"):
                values[agg.alias] = 95 if column == "card_number" else 100
            elif agg.alias.startswith("dc_"):
                values[agg.alias] = self.DISTINCT[column]
            elif agg.alias.startswith("mn_"):
                values[agg.alias] = "2026-07-01" if column == "created_at" else "1.0"
            elif agg.alias.startswith("mx_"):
                values[agg.alias] = "2026-07-31" if column == "created_at" else "99.0"
            elif agg.alias.startswith("av_"):
                values[agg.alias] = 12.5
        return {"columns": [{"name": agg.alias, "type": "Any"} for agg in aggregates],
                "rows": [tuple(values[agg.alias] for agg in aggregates)]}

    async def ping(self, client):
        return {"ok": True}

    async def introspect(self, ctx, connection, source):
        return _CATALOG

    async def close(self, client):
        pass


def _engine():
    registry = ProviderRegistry()
    registry.register(_ProfileProvider())
    return Engine(registry)


def _conn():
    return Connection(id="c1", name="fake", provider="fake", org_id="default",
                      project_id="default")


class TestLooksSensitive(unittest.TestCase):
    def test_sensitive_names(self):
        for name in ("password", "api_key", "user_email", "card_number", "ssn"):
            self.assertTrue(looks_sensitive(name), name)

    def test_plain_names(self):
        for name in ("service_name", "amount", "created_at", "status"):
            self.assertFalse(looks_sensitive(name), name)


class TestSchemaProfiler(unittest.TestCase):
    def _profile(self, **kwargs):
        profiler = SchemaProfiler(_engine())
        return asyncio.run(profiler.profile(
            RequestContext(source="api"), _conn(), _CATALOG, **kwargs))

    def test_profiles_all_columns(self):
        profile = self._profile()
        columns = {c.name: c for c in profile.tables["orders"]}
        self.assertEqual(len(columns), 5)
        self.assertEqual(columns["order_id"].row_count, 100)
        self.assertEqual(columns["order_id"].null_ratio, 0.0)
        self.assertEqual(columns["order_id"].distinct_count, 100)
        self.assertAlmostEqual(columns["order_id"].uniqueness_ratio, 1.0)
        self.assertIn("identifier", columns["order_id"].role_candidates)

    def test_measure_and_min_max(self):
        columns = {c.name: c for c in self._profile().tables["orders"]}
        self.assertIn("measure", columns["amount"].role_candidates)
        self.assertEqual(columns["amount"].min_value, "1.0")
        self.assertEqual(columns["amount"].max_value, "99.0")
        self.assertEqual(columns["amount"].avg_value, 12.5)
        self.assertEqual(len(columns["amount"].top_values), 0)

    def test_dimension_and_temporal(self):
        columns = {c.name: c for c in self._profile().tables["orders"]}
        self.assertIn("dimension", columns["status"].role_candidates)
        self.assertIn("temporal", columns["created_at"].role_candidates)
        self.assertEqual(columns["created_at"].min_value, "2026-07-01")
        self.assertEqual(columns["created_at"].max_value, "2026-07-31")

    def test_sensitive_column_counts_only(self):
        columns = {c.name: c for c in self._profile().tables["orders"]}
        card = columns["card_number"]
        self.assertTrue(card.sensitive)
        self.assertEqual(card.distinct_count, 95)
        self.assertIsNone(card.min_value)
        self.assertIsNone(card.max_value)
        self.assertIsNone(card.avg_value)
        self.assertEqual(card.role_candidates, ())

    def test_envelope_and_table_filter(self):
        profile = self._profile(tables=["missing"])
        self.assertEqual(profile.tables, {})
        full = self._profile()
        self.assertEqual(full.envelope.kind.value, "profile")
        self.assertEqual(full.envelope.provenance.value, "database")

    def test_zero_rows_table(self):
        class _Empty(_ProfileProvider):
            async def compile_and_execute(self, client, plan, ctx):
                aggregates = plan.nodes[0].aggregates
                values = {agg.alias: 0 for agg in aggregates}
                return {"columns": [{"name": a.alias, "type": "Any"} for a in aggregates],
                        "rows": [tuple(values[a.alias] for a in aggregates)]}

        registry = ProviderRegistry()
        registry.register(_Empty())
        profiler = SchemaProfiler(Engine(registry))
        profile = asyncio.run(profiler.profile(
            RequestContext(source="api"), _conn(), _CATALOG))
        columns = {c.name: c for c in profile.tables["orders"]}
        self.assertEqual(columns["order_id"].null_ratio, 0.0)
        self.assertIsNone(columns["order_id"].uniqueness_ratio)


if __name__ == "__main__":
    unittest.main()
