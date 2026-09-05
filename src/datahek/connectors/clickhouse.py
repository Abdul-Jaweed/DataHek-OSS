"""ClickHouse connector — schema introspection, plan → SQL compilation, execution.

The core stays dialect-free; ClickHouse specifics live here (ADR-003).
"""
import asyncio
from typing import Any

from datahek.contracts.connections import Connection
from datahek.contracts.providers import ConnectorCapabilities, DataProvider, ProviderKind, ReadOnlyLevel
from datahek.engine.plan import DEFAULT_LIMIT, LogicalPlan, ReadNode, WriteNode
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext

MAX_INTROSPECT_TABLES = 20


def compile_sql(plan: LogicalPlan) -> str:
    """Compile a read-only LogicalPlan to ClickHouse SQL."""
    if not plan.read_only:
        raise ValueError("Write plans cannot be compiled to SQL")
    node = plan.nodes[0]
    if not isinstance(node, ReadNode):
        raise ValueError(f"Unsupported node type: {type(node).__name__}")

    select_cols = list(node.columns)
    for agg in node.aggregates:
        select_cols.append(f"{agg.function}({agg.column}) AS {agg.alias}")

    sql = f"SELECT {', '.join(select_cols)} FROM {node.source}"
    if node.filter:
        sql += f" WHERE {node.filter}"
    if node.group_by:
        sql += f" GROUP BY {', '.join(node.group_by)}"
    if node.order_by:
        sql += f" ORDER BY {', '.join(node.order_by)}"
    limit = node.limit or DEFAULT_LIMIT
    sql += f" LIMIT {limit}"
    return sql


class ClickHouseProvider(DataProvider):
    provider_id = "clickhouse"
    capabilities = ConnectorCapabilities(
        kind=ProviderKind.SQL,
        dialect="clickhouse",
        features=frozenset({"schema_introspection", "row_counts", "timeouts"}),
        read_only=ReadOnlyLevel.STRUCTURAL,
        max_result_rows=1000,
        max_timeout_s=10,
    )

    async def connect(self, connection: Connection) -> Any:
        from clickhouse_connect import get_client

        return get_client(
            host=connection.host or "localhost",
            port=connection.port or 8123,
            username=connection.settings.get("username", "default"),
            password=connection.settings.get("password", ""),
            database=connection.database or "default",
        )

    async def ping(self, client: Any) -> dict:
        client.query("SELECT 1")
        return {"ok": True}

    async def introspect(self, ctx: RequestContext, connection: Connection, source: str) -> SchemaCatalog:
        client = await self.connect(connection)
        try:
            tables = []
            for name in await asyncio.to_thread(self._list_tables, client):
                columns = await asyncio.to_thread(self._list_columns, client, name)
                row_count = None
                if len(tables) < MAX_INTROSPECT_TABLES:
                    row_count = await asyncio.to_thread(self._row_count, client, name)
                tables.append(TableMeta(name=name, columns=columns, row_count=row_count))
            return SchemaCatalog(source=source, tables=tables)
        finally:
            await self.close(client)

    @staticmethod
    def _list_tables(client: Any) -> list[str]:
        result = client.query(
            "SELECT name FROM system.tables WHERE database = currentDatabase() ORDER BY name"
        )
        return [row[0] for row in getattr(result, "result_rows", []) or []]

    @staticmethod
    def _list_columns(client: Any, table: str) -> list[ColumnMeta]:
        result = client.query(
            "SELECT name, type FROM system.columns "
            f"WHERE database = currentDatabase() AND table = '{table}' ORDER BY position"
        )
        return [ColumnMeta(name=row[0], data_type=row[1]) for row in getattr(result, "result_rows", []) or []]

    @staticmethod
    def _row_count(client: Any, table: str) -> int | None:
        try:
            result = client.query(f"SELECT count() FROM {table}")
            rows = getattr(result, "result_rows", None) or []
            return rows[0][0] if rows else None
        except Exception:
            return None

    async def compile_and_execute(self, client: Any, plan: LogicalPlan, ctx: RequestContext) -> dict:
        sql = compile_sql(plan)
        result = client.query(sql)
        return {
            "columns": [{"name": c, "type": "Any"} for c in (getattr(result, "column_names", None) or [])],
            "rows": list(getattr(result, "result_rows", []) or []),
        }

    async def close(self, client: Any) -> None:
        client.close()