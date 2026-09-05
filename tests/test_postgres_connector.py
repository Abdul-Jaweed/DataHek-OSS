"""PostgreSQL connector — proves the LQP architecture is provider-agnostic."""
import asyncio
import unittest
from unittest import mock

from datahek.connectors.postgres import PostgresProvider
from datahek.contracts.connections import Connection
from datahek.contracts.providers import ProviderKind, ReadOnlyLevel
from datahek.engine.compile import compile_sql
from datahek.engine.plan import Aggregate, LogicalPlan, ReadNode, WriteNode
from datahek.kernel.context import RequestContext


def _conn():
    return Connection(id="c1", name="pg", provider="postgres", org_id="default", project_id="default",
                      host="localhost", port=5432, database="appdb", settings={"username": "app", "password": "x"})


class TestPostgresCapabilities(unittest.TestCase):
    def test_capabilities(self):
        p = PostgresProvider()
        self.assertEqual(p.provider_id, "postgres")
        self.assertEqual(p.capabilities.kind, ProviderKind.SQL)
        self.assertEqual(p.capabilities.dialect, "postgres")
        self.assertEqual(p.capabilities.read_only, ReadOnlyLevel.STRUCTURAL)
        self.assertIn("schema_introspection", p.capabilities.features)


class TestPostgresCompile(unittest.TestCase):
    def test_shared_compiler_produces_postgres_sql(self):
        plan = LogicalPlan(nodes=[
            ReadNode(source="orders", columns=["region"],
                     filter="total_amount > 100", group_by=["region"],
                     aggregates=[Aggregate(function="sum", column="total_amount", alias="revenue")],
                     order_by=["revenue DESC"], limit=10),
        ])
        sql = compile_sql(plan)
        self.assertEqual(
            sql,
            "SELECT region, sum(total_amount) AS revenue FROM orders "
            "WHERE total_amount > 100 GROUP BY region ORDER BY revenue DESC LIMIT 10",
        )

    def test_write_plan_rejected(self):
        plan = LogicalPlan(nodes=[WriteNode(source="t", operation="delete")])
        with self.assertRaises(ValueError):
            compile_sql(plan)


class TestPostgresClient(unittest.TestCase):
    def test_connect_uses_connection_settings(self):
        p = PostgresProvider()
        with mock.patch("datahek.connectors.postgres.psycopg.connect") as m:
            asyncio.run(p.connect(_conn()))
        _, kwargs = m.call_args
        self.assertEqual(kwargs["host"], "localhost")
        self.assertEqual(kwargs["port"], 5432)
        self.assertEqual(kwargs["dbname"], "appdb")
        self.assertEqual(kwargs["user"], "app")

    def test_introspect(self):
        p = PostgresProvider()
        client = mock.Mock()
        client.fetchall.side_effect = [
            [("orders",), ("customers",)],                      # tables
            [("region", "text"), ("total_amount", "numeric")],  # columns (orders)
            [(100,)],                                           # row count
            [("id", "integer")],                                # columns (customers)
            [(50,)],                                            # row count
        ]
        with mock.patch.object(PostgresProvider, "connect", return_value=client):
            cat = asyncio.run(p.introspect(RequestContext(source="api"), _conn(), "c1:appdb"))
        self.assertEqual([t.name for t in cat.tables], ["orders", "customers"])
        self.assertEqual([c.name for c in cat.tables[0].columns], ["region", "total_amount"])
        self.assertEqual(cat.tables[0].row_count, 100)
        sql_used = [c.args[0] for c in client.execute.call_args_list]
        self.assertTrue(any("information_schema.tables" in s for s in sql_used))
        self.assertTrue(any("information_schema.columns" in s for s in sql_used))

    def test_compile_and_execute(self):
        p = PostgresProvider()
        plan = LogicalPlan(nodes=[ReadNode(source="orders", columns=["region"], limit=10)])
        client = mock.Mock()
        client.fetchall.return_value = [("west",), ("east",)]
        out = asyncio.run(p.compile_and_execute(client, plan, RequestContext(source="api")))
        self.assertEqual(out["rows"], [("west",), ("east",)])
        self.assertIn("SELECT region FROM orders", client.execute.call_args.args[0])

    def test_write_plan_rejected_at_compile(self):
        p = PostgresProvider()
        plan = LogicalPlan(nodes=[WriteNode(source="t", operation="drop")])
        with self.assertRaises(ValueError):
            asyncio.run(p.compile_and_execute(mock.Mock(), plan, RequestContext(source="api")))


class TestRegistryIntegration(unittest.TestCase):
    def test_engine_resolves_postgres(self):
        from datahek.engine.executor import Engine, ProviderRegistry

        registry = ProviderRegistry()
        registry.register(PostgresProvider())
        engine = Engine(registry)
        plan = LogicalPlan(nodes=[ReadNode(source="orders", columns=["region"], limit=5)])
        conn = _conn()
        with mock.patch.object(PostgresProvider, "connect", return_value=mock.Mock()) as m:
            client = m.return_value
            client.fetchall.return_value = [("west",)]
            result = asyncio.run(engine.execute(RequestContext(source="api"), plan, conn))
        self.assertEqual(result.rows, [("west",)])


if __name__ == "__main__":
    unittest.main()