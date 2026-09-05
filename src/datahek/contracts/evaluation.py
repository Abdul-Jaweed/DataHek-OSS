"""Evaluation contracts — score every execution (validity, safety, latency)."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class EvaluationStore(Protocol):
    async def record(self, ctx: object, run: dict) -> None: ...
    async def list(self, ctx: object) -> list[dict]: ...
    async def aggregate(self, ctx: object) -> dict: ...


@runtime_checkable
class EvaluationHook(Protocol):
    async def on_execution_completed(self, ctx: object, *, plan: object, result: object | None,
                                     duration_ms: int, decision: str, failed: bool = False) -> None: ...