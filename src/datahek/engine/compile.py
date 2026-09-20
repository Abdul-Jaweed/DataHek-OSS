"""Shared plan → SQL compiler (ADR-006).

The LogicalPlan compiles to provider SQL; dialect differences live in the
provider, the node model is shared. Supports the common SELECT shape with
optional joins for ClickHouse, PostgreSQL, MySQL, and SQLite.
"""
from datahek.engine.plan import DEFAULT_LIMIT, LogicalPlan, ReadNode


def _qualified(column: str, base: str, has_joins: bool) -> str:
    """Qualify a bare column with the base table when the query joins."""
    if not has_joins or "." in column or column == "*":
        return column
    return f"{base}.{column}"


def compile_sql(plan: LogicalPlan) -> str:
    """Compile a read-only LogicalPlan to SQL (SELECT ... [JOIN ...] LIMIT shape)."""
    if not plan.read_only:
        raise ValueError("Write plans cannot be compiled to SQL")
    node = plan.nodes[0]
    if not isinstance(node, ReadNode):
        raise ValueError(f"Unsupported node type: {type(node).__name__}")

    has_joins = bool(node.joins)

    select_cols = list(node.columns)
    if node.aggregates:
        # With aggregates, only grouped columns are valid in SELECT;
        # stray non-grouped columns (e.g. LLM planning noise) are dropped.
        grouped = set(node.group_by)
        select_cols = [c for c in select_cols if c in grouped]
    select_cols = [_qualified(c, node.source, has_joins) for c in select_cols]
    for agg in node.aggregates:
        col = _qualified(agg.column, node.source, has_joins)
        if agg.function == "count_distinct":
            select_cols.append(f"COUNT(DISTINCT {col}) AS {agg.alias}")
        else:
            select_cols.append(f"{agg.function}({col}) AS {agg.alias}")

    sql = f"SELECT {', '.join(select_cols)} FROM {node.source}"

    for join in node.joins:
        keyword = "LEFT JOIN" if join.join_type == "left" else "INNER JOIN"
        left = join.on_left if "." in join.on_left else f"{node.source}.{join.on_left}"
        right_col = join.on_right or join.on_left.split(".")[-1]
        right = right_col if "." in right_col else f"{join.table}.{right_col}"
        sql += f" {keyword} {join.table} ON {left} = {right}"

    if node.filter:
        sql += f" WHERE {node.filter}"
    if node.group_by:
        grouped = [_qualified(c, node.source, has_joins) for c in node.group_by]
        sql += f" GROUP BY {', '.join(grouped)}"
    if node.order_by:
        sql += f" ORDER BY {', '.join(node.order_by)}"
    limit = node.limit or DEFAULT_LIMIT
    sql += f" LIMIT {limit}"
    return sql
