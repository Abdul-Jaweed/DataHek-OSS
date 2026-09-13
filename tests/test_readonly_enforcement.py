"""Physical read-only enforcement — the database itself must reject writes."""
import asyncio
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from datahek.contracts.connections import Connection


def _conn(provider, host="localhost", **settings):
    return Connection(id="c1", name="x", provider=provider, org_id="default", project_id="default",
                      host=host, port=None, database="db", settings=settings)


class TestPostgresPhysicalReadOnly(unittest.TestCase):
    def test_sets_default_transaction_read_only(self):
        from datahek.connectors.postgres import PostgresProvider

        with mock.patch("datahek.connectors.postgres.psycopg.connect") as m:
            asyncio.run(PostgresProvider().connect(_conn("postgres")))
        client = m.return_value
        executed = [c.args[0] if c.args else "" for c in client.execute.call_args_list]
        self.assertTrue(any("default_transaction_read_only" in s.lower() for s in executed), executed)


class TestSQLitePhysicalReadOnly(unittest.TestCase):
    def test_file_db_opened_read_only(self):
        from datahek.connectors.sqlite import SQLiteProvider

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ro.db")
            seed = sqlite3.connect(path)
            seed.execute("CREATE TABLE t (x INTEGER)")
            seed.execute("INSERT INTO t VALUES (1)")
            seed.commit()
            seed.close()

            client = asyncio.run(SQLiteProvider().connect(_conn("sqlite", host=path)))
            try:
                rows = client.execute("SELECT x FROM t").fetchall()
                self.assertEqual(rows, [(1,)])
                with self.assertRaises(sqlite3.OperationalError):
                    client.execute("INSERT INTO t VALUES (2)")
            finally:
                client.close()

    def test_memory_db_still_works(self):
        from datahek.connectors.sqlite import SQLiteProvider

        client = asyncio.run(SQLiteProvider().connect(_conn("sqlite", host=":memory:")))
        self.assertEqual(client.execute("SELECT 1").fetchone()[0], 1)


class TestMySQLPhysicalReadOnly(unittest.TestCase):
    def test_sets_session_transaction_read_only(self):
        from datahek.connectors.mysql import MySQLProvider

        with mock.patch("datahek.connectors.mysql.pymysql.connect") as m:
            asyncio.run(MySQLProvider().connect(_conn("mysql")))
        client = m.return_value
        cur = client.cursor.return_value
        executed = [c.args[0] if c.args else "" for c in cur.execute.call_args_list]
        self.assertTrue(any("READ ONLY" in s.upper() for s in executed), executed)


class TestClickHousePhysicalReadOnly(unittest.TestCase):
    def test_client_created_readonly(self):
        import sys
        import types

        from datahek.connectors.clickhouse import ClickHouseProvider

        fake_mod = types.ModuleType("clickhouse_connect")
        fake_mod.get_client = mock.Mock(return_value=mock.Mock())
        with mock.patch.dict(sys.modules, {"clickhouse_connect": fake_mod}):
            asyncio.run(ClickHouseProvider().connect(_conn("clickhouse", port=8123)))
        kwargs = fake_mod.get_client.call_args.kwargs
        self.assertEqual(kwargs.get("settings", {}).get("readonly"), 1)


if __name__ == "__main__":
    unittest.main()
