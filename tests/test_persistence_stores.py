"""Durable approvals + checkpoints — survive restarts (SQLite default, PG opt-in)."""
import asyncio
import os
import tempfile
import unittest
from unittest import mock

from datahek.contracts.misc import ApprovalRequest
from datahek.kernel.context import RequestContext

PG_URL = os.environ.get("DATAHEK_TEST_PG_URL")
skip_pg = unittest.skipUnless(PG_URL, "postgres test container not running")


def _request(aid="a1"):
    return ApprovalRequest(id=aid, org_id="default", project_id="default",
                           resource_ref="conn_1", requester="datahek", reason="big export")


class TestSqliteApprovalService(unittest.TestCase):
    def test_lifecycle_and_persistence(self):
        from datahek.defaults.approvals_sqlite import SqliteApprovalService

        with tempfile.TemporaryDirectory() as d:
            path = f"{d}/appr.db"
            a = SqliteApprovalService(path)

            async def run():
                await a.request_approval(RequestContext(source="api"), _request())
                self.assertEqual(await a.status("a1"), "pending")

                # a fresh instance = a process restart
                b = SqliteApprovalService(path)
                self.assertEqual(await b.status("a1"), "pending")  # survived
                await b.decide("a1", "approved", "admin")
                self.assertEqual(await a.status("a1"), "approved")  # visible everywhere
                await a.consume("a1")
                self.assertEqual(await b.status("a1"), "consumed")

            asyncio.run(run())
            self.assertEqual(len(SqliteApprovalService(path).list_all()), 1)

    def test_reject_and_unknown(self):
        from datahek.defaults.approvals_sqlite import SqliteApprovalService
        from datahek.kernel.errors import DatahekError, ErrorCode

        with tempfile.TemporaryDirectory() as d:
            svc = SqliteApprovalService(f"{d}/a.db")

            async def run():
                await svc.request_approval(RequestContext(source="api"), _request("x"))
                await svc.decide("x", "rejected", "admin")
                self.assertEqual(await svc.status("x"), "rejected")
                with self.assertRaises(DatahekError) as cm:
                    await svc.status("nope")
                self.assertEqual(cm.exception.code, ErrorCode.NOT_FOUND)

            asyncio.run(run())


class TestPostgresStores(unittest.TestCase):
    def _pg(self):
        from datahek.defaults.pg import PgMetadata

        pg = PgMetadata(url=PG_URL)
        asyncio.run(pg.init_schema())
        return pg

    @skip_pg
    def test_approval_lifecycle_persists(self):
        from datahek.defaults.approvals_pg import PostgresApprovalService
        import uuid

        pg = self._pg()
        aid = f"a-{uuid.uuid4().hex[:8]}"
        svc = PostgresApprovalService(pg)

        async def run():
            await svc.request_approval(RequestContext(source="api"), _request(aid))
            fresh = PostgresApprovalService(pg)  # new instance = restart
            self.assertEqual(await fresh.status(aid), "pending")
            await fresh.decide(aid, "approved", "admin")
            await fresh.consume(aid)
            self.assertEqual(await svc.status(aid), "consumed")
            listed = await svc.list_all()
            self.assertTrue(any(a["id"] == aid for a in listed))

        asyncio.run(run())

    @skip_pg
    def test_checkpoint_roundtrip(self):
        from datahek.defaults.checkpoints_pg import PostgresCheckpointStore
        import uuid

        pg = self._pg()
        store = PostgresCheckpointStore(pg)
        ctx = RequestContext(source="api")
        q = f"q-{uuid.uuid4().hex[:8]}"

        async def run():
            cid = await store.save(ctx, {
                "question": q, "connection_id": "c1",
                "plan": {"nodes": [{"type": "ReadNode", "source": "traces"}]},
                "sql": "SELECT 1", "row_count": 1, "decision": "ALLOW"})
            fresh = PostgresCheckpointStore(pg)
            item = await fresh.get(ctx, cid)
            self.assertEqual(item["question"], q)
            self.assertEqual(item["sql"], "SELECT 1")
            listed = await fresh.list(ctx, limit=50)
            self.assertTrue(any(i["id"] == cid for i in listed))

        asyncio.run(run())


class TestContainerDurability(unittest.TestCase):
    def test_default_container_uses_durable_stores(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["DATAHEK_DB_PATH"] = f"{d}/db.sqlite"
            try:
                from datahek.defaults.container import build_app_container
                from datahek.contracts.misc import ApprovalService, CheckpointStore

                c = build_app_container()
                self.assertEqual(type(c.resolve(ApprovalService)).__name__, "SqliteApprovalService")
                self.assertEqual(type(c.resolve(CheckpointStore)).__name__, "SqliteCheckpointStore")
            finally:
                os.environ.pop("DATAHEK_DB_PATH", None)


if __name__ == "__main__":
    unittest.main()
