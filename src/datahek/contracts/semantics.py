"""Semantic layer contract — metric definitions the planner prefers over guessing.

A metric is a named, reusable aggregate definition (e.g. "revenue" =
sum(amount) on orders). The planner receives the catalog and resolves
questions like "what was revenue last month?" into validated plans instead
of inventing column semantics.
"""
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Metric:
    id: str
    name: str
    table: str
    aggregate: str  # count, count_distinct, sum, avg, min, max, uniq
    column: str = "*"
    filter: str | None = None
    description: str = ""
    org_id: str = "default"
    project_id: str = "default"


@runtime_checkable
class SemanticStore(Protocol):
    async def create(self, ctx: object, metric: Metric) -> None: ...
    async def get(self, ctx: object, metric_id: str) -> dict | None: ...
    async def update(self, ctx: object, metric_id: str, patch: dict) -> None: ...
    async def delete(self, ctx: object, metric_id: str) -> None: ...
    async def list(self, ctx: object) -> list[dict]: ...
