"""Context rebuild queue — background repair of stale context."""
import asyncio
import unittest

from datahek.context.jobs.build_context import BuildResult
from datahek.context.jobs.rebuild_queue import ContextRebuildQueue
from datahek.contracts.connections import Connection
from datahek.kernel.context import RequestContext
from datahek.kernel.errors import DatahekError


class _FakeJob:
    def __init__(self, fail=False, warnings=()):
        self.fail = fail
        self.warnings = tuple(warnings)
        self.calls: list[dict] = []

    async def run(self, ctx, connection, provider, *, tables=None, enrichment=True,
                  skip_if_current=True):
        self.calls.append({"connection": connection.id, "tables": tables,
                           "enrichment": enrichment, "org": ctx.organization_id})
        if self.fail:
            raise RuntimeError("database down")
        return BuildResult(connection_id=connection.id, state="active",
                           context_id="ctx-1", version=3,
                           warnings=self.warnings)


class _FakeConnections:
    async def get_connection(self, ctx, connection_id):
        return Connection(id=connection_id, name="fake", provider="fake",
                          org_id=ctx.organization_id, project_id="default")


class _FakeProviders:
    def get(self, provider_id):
        return object()


def _queue(job):
    return ContextRebuildQueue(job, registry_service=object(),
                               connection_manager=_FakeConnections(),
                               provider_registry=_FakeProviders())


class TestRebuildQueue(unittest.TestCase):
    def setUp(self):
        self.job = _FakeJob()
        self.queue = _queue(self.job)
        self.ctx = RequestContext(source="cli", organization_id="acme", user_id="alice")

    def test_enqueue_and_run_pending(self):
        job = asyncio.run(self.queue.enqueue(self.ctx, "conn-1"))
        self.assertEqual(job["state"], "queued")
        self.assertEqual(self.queue.queued_count(), 1)
        processed = asyncio.run(self.queue.run_pending())
        self.assertEqual(processed, 1)
        record = self.queue.status(job["id"])
        self.assertEqual(record["state"], "completed")
        self.assertEqual(record["version"], 3)
        self.assertEqual(record["context_id"], "ctx-1")
        self.assertEqual(self.job.calls[0]["connection"], "conn-1")
        self.assertEqual(self.job.calls[0]["org"], "acme")
        self.assertEqual(self.job.calls[0]["enrichment"], False)

    def test_enqueue_deduplicates_active_jobs(self):
        first = asyncio.run(self.queue.enqueue(self.ctx, "conn-1"))
        second = asyncio.run(self.queue.enqueue(self.ctx, "conn-1"))
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.queue.queued_count(), 1)

    def test_reenqueue_after_completion(self):
        first = asyncio.run(self.queue.enqueue(self.ctx, "conn-1"))
        asyncio.run(self.queue.run_pending())
        second = asyncio.run(self.queue.enqueue(self.ctx, "conn-1"))
        self.assertNotEqual(first["id"], second["id"])

    def test_failure_recorded(self):
        queue = _queue(_FakeJob(fail=True))
        job = asyncio.run(queue.enqueue(self.ctx, "conn-1"))
        asyncio.run(queue.run_pending())
        record = queue.status(job["id"])
        self.assertEqual(record["state"], "failed")
        self.assertIn("database down", record["error"])

    def test_warnings_surface_on_success(self):
        queue = _queue(_FakeJob(warnings=("graph unavailable",)))
        job = asyncio.run(queue.enqueue(self.ctx, "conn-1"))
        asyncio.run(queue.run_pending())
        self.assertIn("graph unavailable", queue.status(job["id"])["error"])

    def test_tables_and_enrichment_forwarded(self):
        asyncio.run(self.queue.enqueue(self.ctx, "conn-1", enrichment=True,
                                       tables=["orders"]))
        asyncio.run(self.queue.run_pending())
        self.assertEqual(self.job.calls[0]["tables"], ["orders"])
        self.assertEqual(self.job.calls[0]["enrichment"], True)

    def test_status_filtered_by_organization(self):
        asyncio.run(self.queue.enqueue(self.ctx, "conn-1"))
        other = RequestContext(source="cli", organization_id="other")
        asyncio.run(self.queue.enqueue(other, "conn-2"))
        self.assertEqual(len(self.queue.status(org_id="acme")), 1)
        self.assertEqual(self.queue.status(org_id="other")[0]["connection_id"], "conn-2")

    def test_unknown_job_not_found(self):
        with self.assertRaises(DatahekError) as caught:
            self.queue.status("missing")
        self.assertEqual(caught.exception.code.value, "NOT_FOUND")

    def test_background_worker_drains_queue(self):
        async def scenario():
            await self.queue.start()
            job = await self.queue.enqueue(self.ctx, "conn-1")
            for _ in range(50):
                await asyncio.sleep(0.02)
                if self.queue.status(job["id"])["state"] == "completed":
                    break
            await self.queue.stop()
            return self.queue.status(job["id"])["state"]

        self.assertEqual(asyncio.run(scenario()), "completed")
        self.assertFalse(self.queue.running)


if __name__ == "__main__":
    unittest.main()
