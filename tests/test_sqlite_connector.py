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
            m.assert_called_once_with(path)

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


if __name__ == "__main__":
    unittest.main()