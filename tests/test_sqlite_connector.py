"""SQLite connector — zero-dependency (stdlib), file-based data source."""
import asyncio
import sqlite3
import unittest
from unittest import mock

from datahek.connectors.sqlite import SQLiteProvider
from datahek.contracts.connections import Connection
from datahek.contracts.providers import ProviderKind, ReadOnlyLevel
from datahek.engine.compile import compile_sql
from datahek.engine.plan import LogicalPlan, ReadNode, WriteNode
from datahek.kernel.context import RequestContext


def _conn(path="/tmp/datahek-test.db"):
    return Connection(id="c1", name="local", provider="sqlite", org_id="default", project_id="default",
                      host=path)


class TestSQLiteCapabilities(unittest.TestCase):
    def test_capabilities(self):
        p = SQLiteProvider()
        self.assertEqual(p.provider_id, "sqlite")
        self.assertEqual(p.capabilities.kind, ProviderKind.SQL)
        self.assertEqual(p.capabilities.dialect, "sqlite")
        self.assertEqual(p.capabilities.read_only, ReadOnlyLevel.STRUCTURAL)


class TestSQLiteCompile(unittest.TestCase):
    def test_shared_compiler(self):
        plan = LogicalPlan(nodes=[ReadNode(source="orders", columns=["region"], limit=10)])
        self.assertEqual(compile_sql(plan), "SELECT region FROM orders LIMIT 10")

    def test_write_plan_rejected(self):
        with self.assertRaises(ValueError):
            compile_sql(LogicalPlan(nodes=[WriteNode(source="t", operation="delete")]))


class TestSQLiteClient(unittest.TestCase):
    def test_connect_uses_host_as_path(self):
        import tempfile
        from pathlib import Path

        p = SQLiteProvider()
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "app.db")
            conn = _conn(path)
            with mock.patch("datahek.connectors.sqlite.sqlite3.connect") as m:
                asyncio.run(p.connect(conn))
            # Physical read-only enforcement: file DBs open via the read-only URI.
            m.assert_called_once_with(f"file:{path}?mode=ro", uri=True)

    def test_introspect(self):
        import tempfile
        from pathlib import Path

        p = SQLiteProvider()
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "app.db")
            real = sqlite3.connect(path)
            real.execute("CREATE TABLE orders (region TEXT, total REAL)")
            real.execute("INSERT INTO orders VALUES ('west', 100), ('east', 50)")
            real.commit()
            cat = asyncio.run(p.introspect(RequestContext(source="api"), _conn(path), "c1:app.db"))
            self.assertEqual([t.name for t in cat.tables], ["orders"])
            self.assertEqual([c.name for c in cat.tables[0].columns], ["region", "total"])
            self.assertEqual(cat.tables[0].row_count, 2)
            real.close()

    def test_compile_and_execute(self):
        import tempfile
        from pathlib import Path

        p = SQLiteProvider()
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "app.db")
            real = sqlite3.connect(path)
            real.execute("CREATE TABLE orders (region TEXT, total REAL)")
            real.execute("INSERT INTO orders VALUES ('west', 100)")
            real.commit()
            plan = LogicalPlan(nodes=[ReadNode(source="orders", columns=["region"], limit=5)])
            out = asyncio.run(p.compile_and_execute(real, plan, RequestContext(source="api")))
            self.assertEqual(out["rows"], [("west",)])
            real.close()


class TestRegistryIntegration(unittest.TestCase):
    def test_engine_resolves_sqlite(self):
        import tempfile
        from pathlib import Path

        from datahek.engine.executor import Engine, ProviderRegistry

        registry = ProviderRegistry()
        registry.register(SQLiteProvider())
        engine = Engine(registry)
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "app.db")
            real = sqlite3.connect(path)
            real.execute("CREATE TABLE orders (region TEXT)")
            real.execute("INSERT INTO orders VALUES ('west')")
            real.commit()
            conn = _conn(path)
            with mock.patch.object(SQLiteProvider, "connect", return_value=real):
                result = asyncio.run(engine.execute(
                    RequestContext(source="api"),
                    LogicalPlan(nodes=[ReadNode(source="orders", columns=["region"], limit=5)]), conn))
            self.assertEqual(result.rows, [("west",)])
            real.close()


class TestSQLiteConstraintIntrospection(unittest.TestCase):
    def test_constraints_captured(self):
        import tempfile
        from pathlib import Path

        p = SQLiteProvider()
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "app.db")
            real = sqlite3.connect(path)
            real.execute(
                "CREATE TABLE customers (id INTEGER PRIMARY KEY, email TEXT NOT NULL)")
            real.execute(
                "CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL, "
                "amount REAL DEFAULT 0, status TEXT, "
                "FOREIGN KEY (customer_id) REFERENCES customers(id))")
            real.execute("CREATE INDEX idx_orders_status ON orders(status)")
            real.commit()
            cat = asyncio.run(p.introspect(RequestContext(source="api"), _conn(path), "c1:app.db"))
            real.close()

        orders = next(t for t in cat.tables if t.name == "orders")
        self.assertEqual(orders.primary_key, ("id",))
        self.assertEqual(orders.foreign_keys, (("customer_id", "customers.id"),))
        self.assertIn("idx_orders_status", orders.indexes)
        by_name = {c.name: c for c in orders.columns}
        self.assertTrue(by_name["id"].is_primary_key)
        self.assertTrue(by_name["customer_id"].is_foreign_key)
        self.assertEqual(by_name["customer_id"].references, "customers.id")
        self.assertFalse(by_name["customer_id"].nullable)
        self.assertTrue(by_name["status"].nullable)
        self.assertEqual(by_name["amount"].default, "0")
        self.assertEqual([c.ordinal for c in orders.columns], [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()