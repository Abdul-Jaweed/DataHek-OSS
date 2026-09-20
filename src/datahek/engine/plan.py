"""Logical plan model (ADR-006) — versioned, serializable, provider-agnostic.

The agent emits LogicalPlans; providers compile them. Guardrails operate on
the plan. Write nodes are structurally separated — read-only is enforced by
construction.
"""
import os
from dataclasses import dataclass, field
from typing import Any, Literal

from datahek.kernel.errors import DatahekError, ErrorCode

PLAN_VERSION = 1
DEFAULT_LIMIT = int(os.environ.get("DATAHEK_DEFAULT_LIMIT", "10"))


@dataclass(frozen=True)
class PlanNode:
    """Base class for plan nodes."""


@dataclass(frozen=True)
class Aggregate:
    function: str  # count, sum, avg, min, max, uniq
    column: str
    alias: str


@dataclass(frozen=True)
class Join:
    """A single join against the node's base source.

    Column references may be dotted ("table.column"); plain names resolve
    against the base source (and the join's own table for on_right).
    """

    table: str
    on_left: str
    on_right: str | None = None
    join_type: Literal["inner", "left"] = "inner"


@dataclass(frozen=True)
class ReadNode(PlanNode):
    source: str
    columns: list[str] = field(default_factory=list)
    filter: str | None = None
    group_by: list[str] = field(default_factory=list)
    aggregates: list[Aggregate] = field(default_factory=list)
    order_by: list[str] = field(default_factory=list)
    limit: int | None = None
    joins: list[Join] = field(default_factory=list)


@dataclass(frozen=True)
class WriteNode(PlanNode):
    source: str
    operation: Literal["insert", "update", "delete"]
    payload: dict = field(default_factory=dict)


def _normalize_order(entry: Any) -> str:
    """Accept both 'col DESC' strings and {'column','direction'} objects."""
    if isinstance(entry, dict):
        column = entry.get("column", "")
        direction = (entry.get("direction") or "ASC").upper()
        return f"{column} {direction}".strip()
    return str(entry)


@dataclass(frozen=True)
class LogicalPlan:
    version: int = PLAN_VERSION
    nodes: list[PlanNode] = field(default_factory=list)

    @property
    def read_only(self) -> bool:
        return not any(isinstance(n, WriteNode) for n in self.nodes)

    def to_dict(self) -> dict[str, Any]:
        def node_dict(n: PlanNode) -> dict[str, Any]:
            d = {"type": type(n).__name__}
            d.update({
                k: v for k, v in n.__dict__.items()
                if not k.startswith("_")
            })
            if isinstance(n, ReadNode):
                d["aggregates"] = [
                    {"function": a.function, "column": a.column, "alias": a.alias}
                    for a in n.aggregates
                ]
                d["joins"] = [
                    {"table": j.table, "on_left": j.on_left, "on_right": j.on_right,
                     "join_type": j.join_type}
                    for j in n.joins
                ]
            return d

        return {"version": self.version, "nodes": [node_dict(n) for n in self.nodes]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LogicalPlan":
        nodes = []
        for nd in data["nodes"]:
            kind = nd.pop("type")
            if kind == "ReadNode":
                nd["aggregates"] = [Aggregate(**a) for a in nd.get("aggregates", [])]
                nd["order_by"] = [_normalize_order(o) for o in nd.get("order_by", [])]
                nd["joins"] = [Join(**j) for j in nd.get("joins", [])]
                nodes.append(ReadNode(**nd))
            elif kind == "WriteNode":
                nodes.append(WriteNode(**nd))
            else:
                raise DatahekError(ErrorCode.PLAN_INVALID, f"Unknown node type: {kind}")
        return cls(version=data.get("version", PLAN_VERSION), nodes=nodes)


# Aggregate functions allowed per SQL dialect (planner vocabulary).
# "count_distinct" renders as COUNT(DISTINCT col) — the portable distinct count.
_AGGREGATE_FUNCTIONS = {
    "clickhouse": frozenset({"count", "count_distinct", "sum", "avg", "min", "max", "uniq"}),
    "postgres": frozenset({"count", "count_distinct", "sum", "avg", "min", "max"}),
    "mysql": frozenset({"count", "count_distinct", "sum", "avg", "min", "max"}),
    "sqlite": frozenset({"count", "count_distinct", "sum", "avg", "min", "max"}),
    "duckdb": frozenset({"count", "count_distinct", "sum", "avg", "min", "max"}),
}
_DEFAULT_FUNCTIONS = frozenset().union(*_AGGREGATE_FUNCTIONS.values())

_NUMERIC_HINTS = ("int", "float", "double", "decimal", "numeric", "real", "serial", "money", "uint", "number")


def type_family(type_name: str) -> str:
    lowered = (type_name or "").lower()
    if any(h in lowered for h in _NUMERIC_HINTS):
        return "number"
    if any(h in lowered for h in ("char", "text", "string", "uuid", "json")):
        return "string"
    if any(h in lowered for h in ("timestamp", "date", "time")):
        return "time"
    if "bool" in lowered:
        return "bool"
    return "other"


def validate_plan(
    plan: LogicalPlan,
    tables: set[str],
    columns: dict[str, set[str]],
    dialect: str | None = None,
    column_types: dict[str, dict[str, str]] | None = None,
) -> None:
    """Validate the plan against a schema catalog. Raises PLAN_INVALID."""
    if not plan.nodes:
        raise DatahekError(ErrorCode.PLAN_INVALID, "Plan contains no read nodes")
    allowed_functions = _AGGREGATE_FUNCTIONS.get(dialect, _DEFAULT_FUNCTIONS)
    types = column_types or {}

    def _type_of(col: str, default_table: str) -> str | None:
        if col == "*" or "." in col:
            table, _, bare = col.partition(".")
            lookup_table = table if bare else default_table
            bare = bare or col
        else:
            lookup_table, bare = default_table, col
        return types.get(lookup_table, {}).get(bare)

    for node in plan.nodes:
        if isinstance(node, WriteNode):
            continue
        if node.source not in tables:
            raise DatahekError(
                ErrorCode.PLAN_INVALID,
                f"Unknown source '{node.source}'",
                details={"source": node.source},
            )
        known = columns.get(node.source, set())

        def _resolve(col: str, default_table: str, context: str) -> None:
            if col == "*" and node.aggregates:
                return  # count(*)-style: dropped by the compiler when aggregating
            if "." in col:
                table, _, bare = col.partition(".")
                if table not in join_tables and table != node.source:
                    raise DatahekError(
                        ErrorCode.PLAN_INVALID,
                        f"Unknown table '{table}' in column '{col}' ({context})",
                        details={"column": col, "source": node.source},
                    )
                if bare not in columns.get(table, set()):
                    raise DatahekError(
                        ErrorCode.PLAN_INVALID,
                        f"Unknown column '{bare}' on '{table}'",
                        details={"column": bare, "source": table},
                    )
                return
            if col not in columns.get(default_table, set()):
                raise DatahekError(
                    ErrorCode.PLAN_INVALID,
                    f"Unknown column '{col}' on '{default_table}'",
                    details={"column": col, "source": default_table},
                )

        # join tables must exist in the schema
        join_tables = {j.table for j in node.joins}
        for j in node.joins:
            if j.table not in tables:
                raise DatahekError(
                    ErrorCode.PLAN_INVALID,
                    f"Unknown join table '{j.table}'",
                    details={"table": j.table, "source": node.source},
                )
            # on_left: base source (or dotted); on_right: joined table
            _resolve(j.on_left, node.source, "join condition")
            if j.on_right:
                _resolve(j.on_right, j.table, "join condition")
            left_type = _type_of(j.on_left, node.source)
            right_type = _type_of(j.on_right, j.table) if j.on_right else None
            if left_type and right_type:
                left_family, right_family = type_family(left_type), type_family(right_type)
                if "other" not in (left_family, right_family) and left_family != right_family:
                    raise DatahekError(
                        ErrorCode.PLAN_INVALID,
                        f"Join columns have incompatible types: '{j.on_left}' is {left_type}, "
                        f"'{j.on_right}' is {right_type}",
                        details={"on_left": j.on_left, "on_right": j.on_right},
                    )

        for col in node.columns:
            _resolve(col, node.source, "select")
        def _bare(name: str) -> str:
            return name.split(".")[-1]

        for col in node.group_by:
            if col in node.columns:
                continue
            if any(_bare(col) == _bare(c) for c in node.columns):
                continue
            raise DatahekError(
                ErrorCode.PLAN_INVALID,
                f"GROUP BY column '{col}' must be in SELECT columns",
            )
        for agg in node.aggregates:
            if agg.function not in allowed_functions:
                raise DatahekError(
                    ErrorCode.PLAN_INVALID,
                    f"Aggregate function '{agg.function}' is not supported on dialect '{dialect or 'any'}'",
                    details={"function": agg.function, "dialect": dialect},
                )
            if agg.function in ("sum", "avg") and agg.column != "*":
                col_type = _type_of(agg.column, node.source)
                if col_type and not any(h in col_type.lower() for h in _NUMERIC_HINTS):
                    raise DatahekError(
                        ErrorCode.PLAN_INVALID,
                        f"Aggregate '{agg.function}' requires a numeric column; "
                        f"'{agg.column}' is {col_type}",
                        details={"function": agg.function, "column": agg.column},
                    )
            if agg.function == "count_distinct" and agg.column == "*":
                raise DatahekError(
                    ErrorCode.PLAN_INVALID,
                    "count_distinct requires a real column, not '*'",
                    details={"function": agg.function},
                )
            if agg.column == "*":
                continue  # count(*)
            _resolve(agg.column, node.source, "aggregate")