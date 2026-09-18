"""DuckDB connector — embedded analytics database (single-file, read-only).

DuckDB is to analytics what SQLite is to transactions: a single file, no
server. Files open read-only (duckdb.connect(read_only=True)); ``:memory:``
is available for ephemeral test data.
"""
from typing import Any

from datahek.connectors.sqlite import SQLiteProvider  # reuse the execution shape
from datahek.contracts.connections import Connection
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind, ReadOnlyLevel
from datahek.engine.compile import compile_sql
from datahek.engine.plan import LogicalPlan
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError, ErrorCode

_TABLES_SQL = (
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_schema = 'main' AND table_type = 'BASE TABLE' "
    "ORDER BY table_name"
)
_COLUMNS_SQL = (
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position"
)


class DuckDBProvider(SQLiteProvider):
    provider_id = "duckdb"
    capabilities = ConnectorCapabilities(
        kind=ProviderKind.SQL,
        dialect="duckdb",
        features=frozenset({"schema_introspection", "aggregations", "joins"}),
        read_only=ReadOnlyLevel.STRUCTURAL,
    )

    async def connect(self, connection: Connection) -> Any:
        import duckdb

        target = connection.host or ":memory:"
        if target == ":memory:":
            return duckdb.connect(target)
        # Physical read-only enforcement: DuckDB rejects writes on read-only files.
        return duckdb.connect(target, read_only=True)

    async def ping(self, client: Any) -> dict:
        client.execute("SELECT 1")
        return {"ok": True}

    async def introspect(self, ctx: RequestContext, connection: Connection,
                         source: str) -> SchemaCatalog:
        client = await self.connect(connection)
        try:
            table_names = [row[0] for row in client.execute(_TABLES_SQL).fetchall()]
            tables = []
            for name in table_names:
                cols = client.execute(_COLUMNS_SQL, [name]).fetchall()
                row = client.execute(f'SELECT count(*) FROM "{name}"').fetchone()
                tables.append(TableMeta(
                    name=name,
                    columns=[ColumnMeta(name=c[0], data_type=c[1]) for c in cols],
                    row_count=row[0] if row else None,
                ))
        finally:
            client.close()
        return SchemaCatalog(source=source, tables=tables)

    async def compile_and_execute(self, client: Any, plan: LogicalPlan,
                                  ctx: RequestContext) -> dict:
        import duckdb

        sql = compile_sql(plan)
        try:
            result = client.execute(sql)
            rows = result.fetchall() or []
            columns = [{"name": d[0], "type": "Any"} for d in (result.description or [])]
        except duckdb.Error as e:
            raise DatahekError(ErrorCode.QUERY_FAILED, f"DuckDB rejected the query: {e}",
                               details={"sql": sql}) from e
        return {"columns": columns, "rows": list(rows)}

    async def close(self, client: Any) -> None:
        client.close()
