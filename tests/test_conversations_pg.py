"""Postgres conversation store — mirrors the SQLite conversation store behavior."""
import asyncio
import os
import unittest

from datahek.defaults.conversations_pg import PostgresConversationStore
from datahek.defaults.pg import PgMetadata
from datahek.kernel.context import RequestContext

PG_URL = os.environ.get("DATAHEK_TEST_PG_URL") or "postgresql://datahek:datahek@127.0.0.1:55432/datahek"


def _run(coro):
    return asyncio.run(coro)


@unittest.skipUnless(os.environ.get("DATAHEK_TEST_PG_URL"), "postgres test container not running")
class TestPostgresConversationStore(unittest.TestCase):
    def setUp(self):
        self.pg = PgMetadata(url=PG_URL)

        async def setup():
            await self.pg.init_schema()
            conn = await self.pg.connect()
            try:
                conn.execute("TRUNCATE messages, conversations, prompts RESTART IDENTITY CASCADE")
            finally:
                conn.close()

        _run(setup())
        self.store = PostgresConversationStore(self.pg)
        self.ctx = RequestContext(source="api", user_id="alice")

    def test_create_and_get(self):
        _run(self.store.create(self.ctx, "conv_1", title="first"))
        conv = _run(self.store.get(self.ctx, "conv_1"))
        self.assertEqual(conv["id"], "conv_1")
        self.assertEqual(conv["title"], "first")
        self.assertEqual(conv["messages"], [])

    def test_append_and_get_messages(self):
        _run(self.store.create(self.ctx, "conv_1"))
        _run(self.store.append_message(self.ctx, "conv_1", {"role": "user", "content": "hello"}))
        _run(self.store.append_message(self.ctx, "conv_1", {"role": "assistant", "content": "hi", "message_type": "answer"}))
        conv = _run(self.store.get(self.ctx, "conv_1"))
        self.assertEqual(len(conv["messages"]), 2)
        self.assertEqual(conv["messages"][0]["role"], "user")
        self.assertEqual(conv["messages"][1]["message_type"], "answer")

    def test_unknown_conversation_returns_none(self):
        self.assertIsNone(_run(self.store.get(self.ctx, "conv_nope")))

    def test_append_to_unknown_raises(self):
        with self.assertRaises(KeyError):
            _run(self.store.append_message(self.ctx, "conv_nope", {"role": "user", "content": "x"}))

    def test_tenant_scoping(self):
        _run(self.store.create(self.ctx, "conv_1"))
        other = RequestContext(source="api", organization_id="other-org", project_id="other")
        self.assertIsNone(_run(self.store.get(other, "conv_1")))
        with self.assertRaises(PermissionError):
            _run(self.store.append_message(other, "conv_1", {"role": "user", "content": "x"}))

    def test_list_by_project(self):
        _run(self.store.create(self.ctx, "conv_1", title="a"))
        _run(self.store.create(self.ctx, "conv_2", title="b"))
        page = _run(self.store.list_by_project(self.ctx, self.ctx.project_id))
        ids = [c["id"] for c in page["items"]]
        self.assertEqual(set(ids), {"conv_1", "conv_2"})
        self.assertIsNone(page["next_cursor"])

    def test_list_by_project_scoped(self):
        _run(self.store.create(self.ctx, "conv_1"))
        other = RequestContext(source="api", organization_id="o2", project_id="p2")
        _run(self.store.create(other, "conv_2"))
        page = _run(self.store.list_by_project(self.ctx, self.ctx.project_id))
        self.assertEqual([c["id"] for c in page["items"]], ["conv_1"])

    def test_persistence_across_instances(self):
        _run(self.store.create(self.ctx, "conv_1"))
        _run(self.store.append_message(self.ctx, "conv_1", {"role": "user", "content": "persisted"}))
        store2 = PostgresConversationStore(self.pg)
        conv = _run(store2.get(self.ctx, "conv_1"))
        self.assertEqual(conv["messages"][0]["content"], "persisted")

    def test_delete_conversation_cascades_messages(self):
        _run(self.store.create(self.ctx, "conv_1"))
        _run(self.store.append_message(self.ctx, "conv_1", {"role": "user", "content": "bye"}))
        conn = _run(self.pg.connect())
        try:
            conn.execute("DELETE FROM conversations WHERE id = %s AND org_id = %s",
                         ("conv_1", self.ctx.organization_id))
        finally:
            conn.close()
        self.assertIsNone(_run(self.store.get(self.ctx, "conv_1")))
        conn = _run(self.pg.connect())
        try:
            row = conn.execute(
                "SELECT 1 FROM messages WHERE conversation_id = %s", ("conv_1",)
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
