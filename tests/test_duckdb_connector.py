"""DuckDB connector — real file, real execution, physical read-only."""
import asyncio
import os
import tempfile
import unittest

import duckdb

from datahek.connectors.duckdb import DuckDBProvider
from datahek.contracts.connections import Connection
from datahek.contracts.providers import ProviderKind
from datahek.engine.compile import compile_sql
from datahek.engine.plan import Aggregate, LogicalPlan, ReadNode
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode


def _conn(path):
    return Connection(id="d1", name="duck", provider="duckdb", org_id="default",
                      project_id="default", host=path, database="main")


def _seed(path):
    conn = duckdb.connect(path)
    conn.execute("CREATE TABLE events (service TEXT, status TEXT, duration_ms INTEGER)")
    conn.executemany("INSERT INTO events VALUES (?, ?, ?)", [
        ("auth", "ok", 150), ("auth", "error", 1200), ("order", "ok", 95),
    ])
    conn.close()


class TestDuckDBCapabilities(unittest.TestCase):
    def test_capabilities(self):
        p = DuckDBProvider()
        self.assertEqual(p.provider_id, "duckdb")
        self.assertEqual(p.capabilities.kind, ProviderKind.SQL)
        self.assertEqual(p.capabilities.dialect, "duckdb")


class TestDuckDBClient(unittest.TestCase):
    def test_introspect_and_query(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "analytics.duckdb")
            _seed(path)
            p = DuckDBProvider()
            ctx = RequestContext(source="api")

            catalog = asyncio.run(p.introspect(ctx, _conn(path), "d1:main"))
            self.assertEqual([t.name for t in catalog.tables], ["events"])
            self.assertEqual([c.name for c in catalog.tables[0].columns],
                             ["service", "status", "duration_ms"])
            self.assertEqual(catalog.tables[0].row_count, 3)

            plan = LogicalPlan(nodes=[ReadNode(
                source="events", columns=["service"], group_by=["service"],
                aggregates=[Aggregate(function="count", column="*", alias="n")],
                order_by=["n DESC"], limit=10)])
            client = asyncio.run(p.connect(_conn(path)))
            out = asyncio.run(p.compile_and_execute(client, plan, ctx))
            self.assertEqual(out["rows"], [("auth", 2), ("order", 1)])

    def test_file_is_physically_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "analytics.duckdb")
            _seed(path)
            p = DuckDBProvider()
            client = asyncio.run(p.connect(_conn(path)))
            try:
                with self.assertRaises(Exception):
                    client.execute("INSERT INTO events VALUES ('x', 'ok', 1)")
                self.assertEqual(client.execute("SELECT count(*) FROM events").fetchone()[0], 3)
            finally:
                client.close()

    def test_invalid_query_maps_to_query_failed(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.duckdb")
            _seed(path)
            p = DuckDBProvider()
            plan = LogicalPlan(nodes=[ReadNode(source="events", columns=["nope"], limit=5)])
            client = asyncio.run(p.connect(_conn(path)))

            async def run():
                out = await p.compile_and_execute(client, plan, RequestContext(source="api"))
                return out

            # Column error surfaces as QUERY_FAILED (compiled SQL hits the engine)
            with self.assertRaises(DatahekError) as cm:
                asyncio.run(run())
            self.assertEqual(cm.exception.code, ErrorCode.QUERY_FAILED)

    def test_compiled_sql_uses_shared_compiler(self):
        plan = LogicalPlan(nodes=[ReadNode(source="events", columns=["service"], limit=5)])
        self.assertEqual(compile_sql(plan), "SELECT service FROM events LIMIT 5")


if __name__ == "__main__":
    unittest.main()
