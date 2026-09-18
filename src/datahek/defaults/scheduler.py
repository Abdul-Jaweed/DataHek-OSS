"""LocalScheduler — in-process schedule runner (OSS default).

Every tick, due schedules run their saved query through the FULL guarded
pipeline (same planner, guardrails, audit, checkpoints as an interactive ask).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class LocalScheduler:
    def __init__(self, store, runner, poll_seconds: float = 30.0) -> None:
        self._store = store
        self._runner = runner
        self._poll_seconds = poll_seconds
        self._task: asyncio.Task | None = None

    async def tick(self, ctx) -> int:
        """Run every due schedule once; returns how many ran."""
        now = datetime.now(timezone.utc)
        due = await self._store.due_schedules(ctx, now.isoformat())
        ran = 0
        for schedule in due:
            status, rows, detail = await self._execute(ctx, schedule)
            next_run = (now + timedelta(seconds=max(schedule["interval_seconds"], 1))).isoformat()
            await self._store.mark_schedule_run(ctx, schedule["id"], status, rows, detail, next_run)
            ran += 1
        return ran

    async def _execute(self, ctx, schedule: dict):
        try:
            result = await self._runner(ctx, schedule)
            return result.get("status", "ok"), result.get("rows"), result.get("detail", "")
        except Exception as exc:
            logger.warning("Scheduled query %s failed: %s", schedule["id"], exc)
            return "error", None, str(exc)

    async def start(self, ctx) -> None:
        if self._task is not None:
            return

        async def loop():
            while True:
                try:
                    await self.tick(ctx)
                except Exception as exc:  # never let the loop die
                    logger.warning("Scheduler tick failed: %s", exc)
                await asyncio.sleep(self._poll_seconds)

        self._task = asyncio.create_task(loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
