"""PostgreSQL connector — proves the LQP architecture is provider-agnostic.

The core (engine/compile.py) produces the SQL; this provider owns
connection, introspection (information_schema), and execution.
"""
import asyncio
from typing import Any

import psycopg

from datahek.contracts.connections import Connection
from datahek.contracts.providers import ConnectorCapabilities, DataProvider, ProviderKind, ReadOnlyLevel
from datahek.engine.compile import compile_sql
from datahek.engine.plan import LogicalPlan
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext

MAX_INTROSPECT_TABLES = 20

_TABLES_SQL = """
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' ORDER BY table_name
"""
_COLUMNS_SQL = """
SELECT column_name, data_type FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position
"""


class PostgresProvider(DataProvider):
    provider_id = "postgres"
    capabilities = ConnectorCapabilities(
        kind=ProviderKind.SQL,
        dialect="postgres",
        features=frozenset({"schema_introspection", "row_counts", "timeouts"}),
        read_only=ReadOnlyLevel.STRUCTURAL,
        max_result_rows=1000,
        max_timeout_s=10,
    )

    async def connect(self, connection: Connection) -> Any:
        return psycopg.connect(
            host=connection.host or "localhost",
            port=connection.port or 5432,
            dbname=connection.database or "postgres",
            user=connection.settings.get("username", "postgres"),
            password=connection.settings.get("password", ""),
            connect_timeout=10,
        )

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
                cur = client.execute(_COLUMNS_SQL, (name,))
                columns = [ColumnMeta(name=r[0], data_type=r[1]) for r in (cur.fetchall() or [])]
                row_count = None
                if len(tables) < MAX_INTROSPECT_TABLES:
                    try:
                        cur = client.execute(f'SELECT count(*) FROM "{name}"')
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
        cur = client.execute(sql)
        rows = cur.fetchall() or []
        columns = []
        description = getattr(cur, "description", None)
        if description:
            try:
                columns = [{"name": d.name, "type": "Any"} for d in description]
            except TypeError:
                columns = []
        return {"columns": columns, "rows": list(rows)}

    async def close(self, client: Any) -> None:
        client.close()