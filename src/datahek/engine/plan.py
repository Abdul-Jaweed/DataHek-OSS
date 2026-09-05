"""Logical plan model (ADR-003) — versioned, serializable, provider-agnostic.

The agent emits LogicalPlans; providers compile them. Guardrails operate on
the plan. Write nodes are structurally separated — read-only is enforced by
construction.
"""
from dataclasses import dataclass, field
from typing import Any, Literal

from datahek.kernel.errors import DatahekError, ErrorCode

PLAN_VERSION = 1
DEFAULT_LIMIT = 1000


@dataclass(frozen=True)
class PlanNode:
    """Base class for plan nodes."""


@dataclass(frozen=True)
class Aggregate:
    function: str  # count, sum, avg, min, max, uniq
    column: str
    alias: str


@dataclass(frozen=True)
class ReadNode(PlanNode):
    source: str
    columns: list[str] = field(default_factory=list)
    filter: str | None = None
    group_by: list[str] = field(default_factory=list)
    aggregates: list[Aggregate] = field(default_factory=list)
    order_by: list[str] = field(default_factory=list)
    limit: int | None = None


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
                nodes.append(ReadNode(**nd))
            elif kind == "WriteNode":
                nodes.append(WriteNode(**nd))
            else:
                raise DatahekError(ErrorCode.PLAN_INVALID, f"Unknown node type: {kind}")
        return cls(version=data.get("version", PLAN_VERSION), nodes=nodes)


def validate_plan(
    plan: LogicalPlan,
    tables: set[str],
    columns: dict[str, set[str]],
) -> None:
    """Validate the plan against a schema catalog. Raises PLAN_INVALID."""
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
        for col in node.columns:
            if col not in known:
                raise DatahekError(
                    ErrorCode.PLAN_INVALID,
                    f"Unknown column '{col}' on '{node.source}'",
                    details={"column": col, "source": node.source},
                )
        for col in node.group_by:
            if col not in node.columns:
                raise DatahekError(
                    ErrorCode.PLAN_INVALID,
                    f"GROUP BY column '{col}' must be in SELECT columns",
                )