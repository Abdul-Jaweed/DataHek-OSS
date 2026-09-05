"""OSS default evaluation — LocalEvaluator + InMemoryEvaluationStore.

Scores per execution: plan validity, safety (read-only + decision), execution
success, latency (banded). Aggregate pass rate over stored runs.
"""
import logging
from dataclasses import dataclass, field

from datahek.contracts.evaluation import EvaluationHook, EvaluationStore
from datahek.kernel.context import RequestContext
from datahek.kernel.ids import new_id

logger = logging.getLogger(__name__)


def latency_score(seconds: float) -> float:
    if seconds < 1:
        return 1.0
    if seconds < 5:
        return 0.8
    if seconds < 15:
        return 0.5
    return 0.2


@dataclass
class EvaluationRun:
    id: str = field(default_factory=new_id)
    org_id: str = "default"
    project_id: str = "default"
    scores: dict = field(default_factory=dict)
    status: str = "recorded"

    def to_dict(self) -> dict:
        return {"id": self.id, "org_id": self.org_id, "project_id": self.project_id,
                "scores": self.scores, "status": self.status}


class InMemoryEvaluationStore(EvaluationStore):
    def __init__(self):
        self._runs: list[dict] = []

    async def record(self, ctx: RequestContext, run: dict) -> None:
        self._runs.append(run)

    async def list(self, ctx: RequestContext) -> list[dict]:
        return [r for r in self._runs if r["org_id"] == ctx.organization_id]

    async def aggregate(self, ctx: RequestContext) -> dict:
        runs = [r for r in self._runs if r["org_id"] == ctx.organization_id]
        total = len(runs)
        passed = sum(1 for r in runs if r["scores"].get("execution", 0) >= 1.0)
        return {"total": total, "passed": passed,
                "pass_rate": (passed / total) if total else 0.0}


class LocalEvaluator(EvaluationHook):
    def __init__(self, store: EvaluationStore):
        self._store = store

    async def on_execution_completed(self, ctx: RequestContext, *, plan, result, duration_ms: int,
                                     decision: str, failed: bool = False) -> None:
        read_only = getattr(plan, "read_only", True)
        scores = {
            "plan_validity": 1.0,
            "safety": 1.0 if (read_only and decision == "ALLOW") else 0.0,
            "execution": 1.0 if (result is not None and not failed) else 0.0,
            "latency": latency_score(duration_ms / 1000) if not failed else 0.0,
        }
        run = EvaluationRun(org_id=ctx.organization_id, project_id=ctx.project_id, scores=scores)
        await self._store.record(ctx, run.to_dict())
        if scores["safety"] < 1.0:
            logger.warning("Evaluation: unsafe execution recorded (safety=%.1f)", scores["safety"])