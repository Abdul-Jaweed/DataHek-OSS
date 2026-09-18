"""Saved queries + schedules contract — named questions that can run again.

A saved query is a reusable question bound to a connection. A schedule runs a
saved query through the full guarded pipeline on an interval.
"""
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SavedQuery:
    id: str
    name: str
    question: str
    connection_id: str
    org_id: str = "default"
    project_id: str = "default"


@dataclass(frozen=True)
class Schedule:
    id: str
    saved_query_id: str
    interval_seconds: int
    org_id: str = "default"
    project_id: str = "default"
    enabled: bool = True


@runtime_checkable
class SavedQueryStore(Protocol):
    async def create(self, ctx: object, query: SavedQuery) -> None: ...
    async def get(self, ctx: object, query_id: str) -> dict | None: ...
    async def delete(self, ctx: object, query_id: str) -> None: ...

    async def create_schedule(self, ctx: object, schedule: Schedule) -> None: ...
    async def get_schedule(self, ctx: object, schedule_id: str) -> dict | None: ...
    async def list_schedules(self, ctx: object) -> list[dict]: ...
    async def delete_schedule(self, ctx: object, schedule_id: str) -> None: ...
    async def due_schedules(self, ctx: object, now_iso: str) -> list[dict]: ...
    async def mark_schedule_run(self, ctx: object, schedule_id: str,
                                status: str, rows: int | None, detail: str,
                                next_run_iso: str) -> None: ...

    async def list_queries(self, ctx: object) -> list[dict]: ...
