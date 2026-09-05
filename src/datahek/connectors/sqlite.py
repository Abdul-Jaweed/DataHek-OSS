"""SQLite connector — zero-dependency (stdlib), file-based data source.

The connection's ``host`` field holds the database file path (SQLite has no
server). Structural read-only is enforced by the shared engine pipeline.
"""
from typing import Any

import sqlite3

from datahek.contracts.connections import Connection
from datahek.contracts.providers import ConnectorCapabilities, DataProvider, ProviderKind, ReadOnlyLevel
from datahek.engine.compile import compile_sql
from datahek.engine.plan import LogicalPlan
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext

MAX_INTROSPECT_TABLES = 20

_TABLES_SQL = "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"


class SQLiteProvider(DataProvider):
    provider_id = "sqlite"
    capabilities = ConnectorCapabilities(
        kind=ProviderKind.SQL,
        dialect="sqlite",
        features=frozenset({"schema_introspection", "row_counts"}),
        read_only=ReadOnlyLevel.STRUCTURAL,
        max_result_rows=1000,
        max_timeout_s=10,
    )

    async def connect(self, connection: Connection) -> Any:
        return sqlite3.connect(connection.host or ":memory:")

    async def ping(self, client: Any) -> dict:
        client.execute("SELECT 1")
        return {"ok": True}

    async def introspect(self, ctx: RequestContext, connection: Connection, source: str) -> SchemaCatalog:
        client = await self.connect(connection)
        try:
            tables = []
            cur = client.execute(_TABLES_SQL)
            names = [row[0] for row in (cur.fetchall() or [])]
            for name in names:
                cols = client.execute(f'PRAGMA table_info("{name}")').fetchall()
                columns = [ColumnMeta(name=row[1], data_type=row[2]) for row in cols]
                row_count = None
                if len(tables) < MAX_INTROSPECT_TABLES:
                    try:
                        rows = client.execute(f'SELECT count(*) FROM "{name}"').fetchall()
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
            cur = client.execute(sql)
        except sqlite3.OperationalError as e:
            raise DatahekError(ErrorCode.QUERY_FAILED, f"SQLite rejected the query: {e}",
                               details={"sql": sql}) from e
        rows = cur.fetchall() or []
        return {"columns": [{"name": d[0], "type": "Any"} for d in (cur.description or [])],
                "rows": list(rows)}

    async def close(self, client: Any) -> None:
        client.close()