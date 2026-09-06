"""Shared plan → SQL compiler (ADR-003).

The LogicalPlan compiles to provider SQL; dialect differences live in the
provider, the node model is shared. Currently supports the common SELECT
shape for ClickHouse and PostgreSQL.
"""
from datahek.engine.plan import DEFAULT_LIMIT, LogicalPlan, ReadNode


def compile_sql(plan: LogicalPlan) -> str:
    """Compile a read-only LogicalPlan to SQL (SELECT ... LIMIT shape)."""
    if not plan.read_only:
        raise ValueError("Write plans cannot be compiled to SQL")
    node = plan.nodes[0]
    if not isinstance(node, ReadNode):
        raise ValueError(f"Unsupported node type: {type(node).__name__}")

    select_cols = list(node.columns)
    if node.aggregates:
        # With aggregates, only grouped columns are valid in SELECT;
        # stray non-grouped columns (e.g. LLM planning noise) are dropped.
        grouped = set(node.group_by)
        select_cols = [c for c in select_cols if c in grouped]
    for agg in node.aggregates:
        if agg.function == "count_distinct":
            select_cols.append(f"COUNT(DISTINCT {agg.column}) AS {agg.alias}")
        else:
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