"""MySQL connector — shared compiler + information_schema introspection."""
import asyncio
import unittest
from unittest import mock

from datahek.connectors.mysql import MySQLProvider
from datahek.contracts.connections import Connection
from datahek.contracts.providers import ProviderKind, ReadOnlyLevel
from datahek.engine.compile import compile_sql
from datahek.engine.plan import LogicalPlan, ReadNode, WriteNode
from datahek.kernel.context import RequestContext


def _conn():
    return Connection(id="c1", name="my", provider="mysql", org_id="default", project_id="default",
                      host="localhost", port=3306, database="appdb",
                      settings={"username": "app", "password": "x"})


class TestMySQLCapabilities(unittest.TestCase):
    def test_capabilities(self):
        p = MySQLProvider()
        self.assertEqual(p.provider_id, "mysql")
        self.assertEqual(p.capabilities.kind, ProviderKind.SQL)
        self.assertEqual(p.capabilities.dialect, "mysql")
        self.assertEqual(p.capabilities.read_only, ReadOnlyLevel.STRUCTURAL)


class TestMySQLCompile(unittest.TestCase):
    def test_shared_compiler(self):
        plan = LogicalPlan(nodes=[ReadNode(source="orders", columns=["region"], filter="total > 100", limit=10)])
        self.assertEqual(compile_sql(plan), "SELECT region FROM orders WHERE total > 100 LIMIT 10")

    def test_write_plan_rejected(self):
        with self.assertRaises(ValueError):
            compile_sql(LogicalPlan(nodes=[WriteNode(source="t", operation="delete")]))


class TestMySQLClient(unittest.TestCase):
    def test_connect_settings(self):
        p = MySQLProvider()
        with mock.patch("datahek.connectors.mysql.pymysql.connect") as m:
            asyncio.run(p.connect(_conn()))
        kwargs = m.call_args.kwargs
        self.assertEqual(kwargs["host"], "localhost")
        self.assertEqual(kwargs["port"], 3306)
        self.assertEqual(kwargs["database"], "appdb")
        self.assertEqual(kwargs["user"], "app")
        self.assertGreaterEqual(kwargs["connect_timeout"], 5)

    def test_introspect(self):
        p = MySQLProvider()
        client = mock.Mock()

        def cursor(result, description=None):
            return mock.Mock(fetchall=lambda: result, description=description)

        client.cursor.return_value.execute.side_effect = None
        calls = [
            cursor([("orders",), ("customers",)]),
            cursor([("region", "varchar"), ("total", "decimal")]),
            cursor([(100,)]),
            cursor([("id", "int")]),
            cursor([(50,)]),
        ]
        client.cursor.return_value.execute.side_effect = lambda *a: None
        fetch_iter = iter(calls)
        client.cursor.return_value.fetchall.side_effect = lambda: next(fetch_iter).fetchall()
        with mock.patch.object(MySQLProvider, "connect", return_value=client):
            cat = asyncio.run(p.introspect(RequestContext(source="api"), _conn(), "c1:appdb"))
        self.assertEqual([t.name for t in cat.tables], ["orders", "customers"])
        self.assertEqual([c.name for c in cat.tables[0].columns], ["region", "total"])
        self.assertEqual(cat.tables[0].row_count, 100)

    def test_compile_and_execute(self):
        p = MySQLProvider()
        client = mock.Mock()
        client.cursor.return_value = mock.Mock(
            fetchall=lambda: [("west",)], description=[("region",), ("varchar",)])
        plan = LogicalPlan(nodes=[ReadNode(source="orders", columns=["region"], limit=5)])
        out = asyncio.run(p.compile_and_execute(client, plan, RequestContext(source="api")))
        self.assertEqual(out["rows"], [("west",)])
        self.assertIn("SELECT region FROM orders", client.cursor.return_value.execute.call_args.args[0])


class TestRegistryIntegration(unittest.TestCase):
    def test_engine_resolves_mysql(self):
        from datahek.engine.executor import Engine, ProviderRegistry

        registry = ProviderRegistry()
        registry.register(MySQLProvider())
        engine = Engine(registry)
        client = mock.Mock()
        client.cursor.return_value = mock.Mock(
            fetchall=lambda: [("west",)], description=[("region",), ("varchar",)])
        conn = _conn()
        with mock.patch.object(MySQLProvider, "connect", return_value=client):
            result = asyncio.run(engine.execute(
                RequestContext(source="api"), LogicalPlan(nodes=[ReadNode(source="orders", columns=["region"], limit=5)]), conn))
        self.assertEqual(result.rows, [("west",)])


if __name__ == "__main__":
    unittest.main()