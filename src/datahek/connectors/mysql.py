"""MySQL connector — shared compiler + information_schema introspection.

Uses PyMySQL (optional dependency: ``datahek-core[mysql]``).
"""
from typing import Any

import pymysql

from datahek.contracts.connections import Connection
from datahek.kernel.errors import DatahekError, ErrorCode
from datahek.contracts.providers import ConnectorCapabilities, DataProvider, ProviderKind, ReadOnlyLevel
from datahek.engine.compile import compile_sql
from datahek.engine.plan import LogicalPlan
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext

MAX_INTROSPECT_TABLES = 20

_TABLES_SQL = """
SELECT table_name FROM information_schema.tables
WHERE table_schema = DATABASE() ORDER BY table_name
"""
_COLUMNS_SQL = """
SELECT column_name, column_type FROM information_schema.columns
WHERE table_schema = DATABASE() AND table_name = %s ORDER BY ordinal_position
"""


class MySQLProvider(DataProvider):
    provider_id = "mysql"
    capabilities = ConnectorCapabilities(
        kind=ProviderKind.SQL,
        dialect="mysql",
        features=frozenset({"schema_introspection", "row_counts", "timeouts"}),
        read_only=ReadOnlyLevel.STRUCTURAL,
        max_result_rows=1000,
        max_timeout_s=10,
    )

    async def connect(self, connection: Connection) -> Any:
        client = pymysql.connect(
            host=connection.host or "localhost",
            port=connection.port or 3306,
            user=connection.settings.get("username", "root"),
            password=connection.settings.get("password", ""),
            database=connection.database or "",
            connect_timeout=10,
        )
        # Physical read-only enforcement: the server itself rejects writes.
        cursor = client.cursor()
        cursor.execute("SET SESSION TRANSACTION READ ONLY")
        cursor.close()
        return client

    async def ping(self, client: Any) -> dict:
        cur = client.cursor()
        cur.execute("SELECT 1")
        return {"ok": True}

    async def introspect(self, ctx: RequestContext, connection: Connection, source: str) -> SchemaCatalog:
        client = await self.connect(connection)
        try:
            tables = []
            cur = client.cursor()
            cur.execute(_TABLES_SQL)
            names = [row[0] for row in (cur.fetchall() or [])]
            for name in names:
                cur.execute(_COLUMNS_SQL, (name,))
                columns = [ColumnMeta(name=r[0], data_type=r[1]) for r in (cur.fetchall() or [])]
                row_count = None
                if len(tables) < MAX_INTROSPECT_TABLES:
                    try:
                        cur.execute(f'SELECT count(*) FROM `{name}`')
                        rows = cur.fetchall() or []
                        row_count = rows[0][0] if rows else None
                    except Exception:
                        row_count = None
                tables.append(TableMeta(name=name, columns=columns, row_count=row_count))
            return SchemaCatalog(source=source, tables=tables)
        finally:
            await self.close(client)

    async def compile_and_execute(self, client: Any, plan: LogicalPlan, ctx: RequestContext) -> dict:
        sql = compile_sql(plan)
        try:
            cur = client.cursor()
            cur.execute(sql)
        except pymysql.err.ProgrammingError as e:
            raise DatahekError(ErrorCode.QUERY_FAILED, f"MySQL rejected the query: {e}",
                               details={"sql": sql}) from e
        except pymysql.err.OperationalError as e:
            raise DatahekError(ErrorCode.CONNECTION_FAILED, f"MySQL connection error: {e}") from e
        rows = cur.fetchall() or []
        return {"columns": [{"name": d[0], "type": "Any"} for d in (cur.description or [])],
                "rows": list(rows)}

    async def close(self, client: Any) -> None:
        client.close()