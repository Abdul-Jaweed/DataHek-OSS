"""ClickHouse connector — plan → SQL compilation and execution (mocked client)."""
import unittest
from unittest import mock

from datahek.connectors.clickhouse import ClickHouseProvider, compile_sql
from datahek.engine.plan import Aggregate, LogicalPlan, ReadNode
from datahek.contracts.providers import ProviderKind, ReadOnlyLevel
from datahek.kernel.context import RequestContext


class TestCompileSql(unittest.TestCase):
    def test_simple_select(self):
        plan = LogicalPlan(nodes=[ReadNode(source="traces", columns=["service", "duration_ms"], limit=100)])
        sql = compile_sql(plan)
        self.assertEqual(
            sql,
            "SELECT service, duration_ms FROM traces LIMIT 100",
        )

    def test_filter_order_limit(self):
        plan = LogicalPlan(nodes=[
            ReadNode(source="traces", columns=["service"], filter="status = 'error'",
                     order_by=["service"], limit=10),
        ])
        sql = compile_sql(plan)
        self.assertIn("WHERE status = 'error'", sql)
        self.assertIn("ORDER BY service", sql)
        self.assertIn("LIMIT 10", sql)

    def test_aggregate_group_by(self):
        plan = LogicalPlan(nodes=[
            ReadNode(
                source="traces", columns=["service"],
                group_by=["service"],
                aggregates=[Aggregate(function="count", column="*", alias="n")],
                order_by=["n DESC"], limit=5,
            ),
        ])
        sql = compile_sql(plan)
        self.assertIn("count(*) AS n", sql)
        self.assertIn("GROUP BY service", sql)
        self.assertIn("ORDER BY n DESC", sql)

    def test_no_limit_means_default(self):
        plan = LogicalPlan(nodes=[ReadNode(source="t", columns=["a"])])
        self.assertIn("LIMIT 1000", compile_sql(plan))

    def test_capabilities(self):
        p = ClickHouseProvider()
        self.assertEqual(p.provider_id, "clickhouse")
        self.assertEqual(p.capabilities.kind, ProviderKind.SQL)
        self.assertEqual(p.capabilities.dialect, "clickhouse")
        self.assertEqual(p.capabilities.read_only, ReadOnlyLevel.STRUCTURAL)


class TestProviderClient(unittest.TestCase):
    def test_connect_uses_connection_settings(self):
        from datahek.contracts.connections import Connection

        p = ClickHouseProvider()
        conn = Connection(
            id="c1", name="ch", provider="clickhouse",
            org_id="default", project_id="default",
            host="localhost", port=8123, database="otel",
        )
        with mock.patch("clickhouse_connect.get_client") as m:
            asyncio_run(p.connect(conn))
        _, kwargs = m.call_args
        self.assertEqual(kwargs["host"], "localhost")
        self.assertEqual(kwargs["port"], 8123)
        self.assertEqual(kwargs["database"], "otel")

    def test_compile_and_execute(self):
        from datahek.contracts.connections import Connection
        from datahek.kernel.context import RequestContext

        p = ClickHouseProvider()
        plan = LogicalPlan(nodes=[ReadNode(source="traces", columns=["service"], limit=10)])
        client = mock.Mock()
        client.query.return_value = mock.Mock(result_rows=[("api",), ("auth",)], column_names=["service"])
        ctx = RequestContext(source="api")
        out = asyncio_run(p.compile_and_execute(client, plan, ctx))
        client.query.assert_called_once()
        self.assertEqual(out["rows"], [("api",), ("auth",)])

    def test_compile_and_execute_denies_write_plan(self):
        from datahek.engine.plan import WriteNode

        p = ClickHouseProvider()
        plan = LogicalPlan(nodes=[WriteNode(source="t", operation="drop")])
        client = mock.Mock()
        ctx = RequestContext(source="api")
        with self.assertRaises(ValueError):
            asyncio_run(p.compile_and_execute(client, plan, ctx))


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()