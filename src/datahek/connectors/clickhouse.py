"""ClickHouse connector — logical plan → SQL compilation + execution.

The core stays dialect-free; ClickHouse specifics live here (ADR-003).
"""
from typing import Any

from datahek.contracts.connections import Connection
from datahek.contracts.providers import ConnectorCapabilities, DataProvider, ProviderKind, ReadOnlyLevel
from datahek.engine.plan import DEFAULT_LIMIT, LogicalPlan, ReadNode, WriteNode
from datahek.kernel.context import RequestContext


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

    async def compile_and_execute(self, client: Any, plan: LogicalPlan, ctx: RequestContext) -> dict:
        sql = compile_sql(plan)
        timeout = ctx.entitlements  # placeholder: timeout policy later
        result = client.query(sql)
        return {
            "columns": [{"name": c, "type": "Any"} for c in (getattr(result, "column_names", None) or [])],
            "rows": list(getattr(result, "result_rows", []) or []),
        }

    async def close(self, client: Any) -> None:
        client.close()