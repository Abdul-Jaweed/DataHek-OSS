"""Context rebuild queue — background, tenant-aware, bounded.

Stale or invalidated context is repaired by enqueuing a connection; a single
background worker drains the queue so request paths never block on a build. The
worker lives in the API lifespan and is safe no-op when no build job is wired.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field

from datahek.kernel.ids import entity_id

logger = logging.getLogger(__name__)

_TERMINAL = ("completed", "failed")


@dataclass
class RebuildJob:
    id: str
    org_id: str
    project_id: str
    connection_id: str
    scope: str = "connection"
    enrichment: bool = False
    tables: list[str] | None = None
    requested_by: str = "anonymous"
    state: str = "queued"
    version: int | None = None
    context_id: str | None = None
    error: str = ""
    enqueued_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "org_id": self.org_id, "project_id": self.project_id,
            "connection_id": self.connection_id, "scope": self.scope,
            "enrichment": self.enrichment, "tables": self.tables,
            "requested_by": self.requested_by, "state": self.state,
            "version": self.version, "context_id": self.context_id, "error": self.error,
            "enqueued_at": self.enqueued_at, "finished_at": self.finished_at,
        }


async def maybe_enqueue_rebuild(queue, ctx, connection_id: str, scope: str,
                                stale: bool, enabled: bool) -> dict | None:
    """Enqueue a rebuild when context is stale and auto-rebuild is enabled."""
    if not (stale and enabled and queue is not None):
        return None
    try:
        return await queue.enqueue(ctx, connection_id, scope=scope, enrichment=False)
    except Exception as exc:
        logger.warning("Auto-rebuild enqueue failed: %s", exc)
        return None


class ContextRebuildQueue:
    def __init__(self, job, registry_service, connection_manager, provider_registry,
                 history_limit: int = 50):
        self._job = job
        self._registry_service = registry_service
        self._connection_manager = connection_manager
        self._provider_registry = provider_registry
        self._history_limit = history_limit
        self._jobs: list[RebuildJob] = []
        self._queue: asyncio.Queue[RebuildJob] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._active = False

    @property
    def running(self) -> bool:
        return self._active

    def _record(self, job: RebuildJob) -> None:
        self._jobs.append(job)
        if len(self._jobs) > self._history_limit:
            self._jobs = self._jobs[-self._history_limit:]

    async def enqueue(self, ctx, connection_id: str, scope: str = "connection",
                      enrichment: bool = False, tables: list[str] | None = None) -> dict:
        existing = next((job for job in self._jobs
                         if job.connection_id == connection_id
                         and job.scope == scope
                         and job.org_id == ctx.organization_id
                         and job.state not in _TERMINAL), None)
        if existing is not None:
            return existing.to_dict()
        job = RebuildJob(
            id=entity_id("request"), org_id=ctx.organization_id,
            project_id=ctx.project_id, connection_id=connection_id, scope=scope,
            enrichment=enrichment, tables=list(tables) if tables else None,
            requested_by=ctx.user_id)
        self._record(job)
        await self._queue.put(job)
        return job.to_dict()

    async def _execute(self, job: RebuildJob) -> None:
        from datahek.context.jobs.build_context import BuildResult

        job.state = "running"
        try:
            from datahek.kernel.context import RequestContext

            ctx = RequestContext(source="worker", user_id=job.requested_by,
                                 organization_id=job.org_id, project_id=job.project_id)
            connection = await self._connection_manager.get_connection(ctx, job.connection_id)
            provider = self._provider_registry.get(connection.provider)
            result: BuildResult = await self._job.run(
                ctx, connection, provider, tables=job.tables,
                enrichment=job.enrichment, skip_if_current=True)
            job.state = "completed" if result.state in ("active", "current") else result.state
            job.version = result.version
            job.context_id = result.context_id
            if result.warnings:
                job.error = "; ".join(result.warnings)[:300]
        except Exception as exc:
            logger.warning("Context rebuild failed for %s: %s", job.connection_id, exc)
            job.state = "failed"
            job.error = str(exc)[:300]
        finally:
            job.finished_at = time.time()

    async def _drain(self) -> None:
        while self._active:
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                await self._execute(job)
            finally:
                self._queue.task_done()

    async def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._worker = asyncio.create_task(self._drain())

    async def stop(self) -> None:
        self._active = False
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    async def run_pending(self) -> int:
        """Drain queued jobs synchronously (used by tests and CLI)."""
        processed = 0
        while not self._queue.empty():
            job = await self._queue.get()
            try:
                await self._execute(job)
            finally:
                self._queue.task_done()
            processed += 1
        return processed

    def status(self, job_id: str | None = None, org_id: str | None = None) -> dict | list:
        jobs = self._jobs
        if org_id:
            jobs = [job for job in jobs if job.org_id == org_id]
        if job_id:
            job = next((job for job in jobs if job.id == job_id), None)
            if job is None:
                from datahek.kernel.errors import DatahekError, ErrorCode

                raise DatahekError(ErrorCode.NOT_FOUND, f"Rebuild job '{job_id}' not found")
            return job.to_dict()
        return [job.to_dict() for job in jobs]

    def queued_count(self) -> int:
        return self._queue.qsize()
