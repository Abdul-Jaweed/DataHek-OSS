"""PostgreSQL connector — proves the LQP architecture is provider-agnostic.

The core (engine/compile.py) produces the SQL; this provider owns
connection, introspection (information_schema), and execution.
"""
import asyncio
from typing import Any

import psycopg

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
WHERE table_schema = 'public' ORDER BY table_name
"""
_COLUMNS_SQL = """
SELECT column_name, data_type, is_nullable, column_default, ordinal_position
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position
"""
_PK_SQL = """
SELECT kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
WHERE tc.table_schema = 'public' AND tc.table_name = %s
  AND tc.constraint_type = 'PRIMARY KEY'
ORDER BY kcu.ordinal_position
"""
_FK_SQL = """
SELECT kcu.column_name, ccu.table_name, ccu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
  ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
WHERE tc.table_schema = 'public' AND tc.table_name = %s
  AND tc.constraint_type = 'FOREIGN KEY'
ORDER BY kcu.column_name
"""
_INDEXES_SQL = """
SELECT indexname FROM pg_indexes
WHERE schemaname = 'public' AND tablename = %s ORDER BY indexname
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
        client = psycopg.connect(
            host=connection.host or "localhost",
            port=connection.port or 5432,
            dbname=connection.database or "postgres",
            user=connection.settings.get("username", "postgres"),
            password=connection.settings.get("password", ""),
            connect_timeout=10,
            sslmode=connection.settings.get("sslmode", "prefer"),
        )
        # Physical read-only enforcement: the server itself rejects writes.
        client.execute("SET default_transaction_read_only = on")
        return client

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
                info = cur.fetchall() or []
                pk_cols = tuple(
                    row[0] for row in (client.execute(_PK_SQL, (name,)).fetchall() or []))
                fk_rows = client.execute(_FK_SQL, (name,)).fetchall() or []
                fk_refs = {row[0]: f"{row[1]}.{row[2]}" for row in fk_rows}
                indexes = tuple(
                    row[0] for row in (client.execute(_INDEXES_SQL, (name,)).fetchall() or []))
                columns = [
                    ColumnMeta(
                        name=row[0],
                        data_type=row[1],
                        nullable=row[2] == "YES",
                        default=row[3],
                        ordinal=row[4],
                        is_primary_key=row[0] in pk_cols,
                        is_foreign_key=row[0] in fk_refs,
                        references=fk_refs.get(row[0]),
                    )
                    for row in info
                ]
                row_count = None
                if len(tables) < MAX_INTROSPECT_TABLES:
                    try:
                        cur = client.execute(f'SELECT count(*) FROM "{name}"')
                        rows = cur.fetchall() or []
                        row_count = rows[0][0] if rows else None
                    except Exception:
                        row_count = None
                tables.append(TableMeta(
                    name=name, columns=columns, row_count=row_count,
                    primary_key=pk_cols,
                    foreign_keys=tuple(sorted(fk_refs.items())),
                    indexes=indexes))
            return SchemaCatalog(source=source, tables=tables)
        finally:
            await self.close(client)

    async def compile_and_execute(self, client: Any, plan: LogicalPlan, ctx: RequestContext) -> dict:
        sql = compile_sql(plan)
        try:
            cur = client.execute(sql)
        except psycopg.errors.ProgrammingError as e:
            raise DatahekError(ErrorCode.QUERY_FAILED, f"PostgreSQL rejected the query: {e}",
                               details={"sql": sql}) from e
        except psycopg.OperationalError as e:
            raise DatahekError(ErrorCode.CONNECTION_FAILED, f"PostgreSQL connection error: {e}") from e
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