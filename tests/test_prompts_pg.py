"""Postgres prompt store — mirrors the SQLite prompt store behavior."""
import asyncio
import os
import unittest

from datahek.defaults.pg import PgMetadata
from datahek.defaults.prompts_pg import PostgresPromptStore
from datahek.kernel.context import RequestContext

PG_URL = os.environ.get("DATAHEK_TEST_PG_URL") or "postgresql://datahek:datahek@127.0.0.1:55432/datahek"


def _run(coro):
    return asyncio.run(coro)


@unittest.skipUnless(os.environ.get("DATAHEK_TEST_PG_URL"), "postgres test container not running")
class TestPostgresPromptStore(unittest.TestCase):
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
        self.store = PostgresPromptStore(self.pg)
        self.ctx = RequestContext(source="api")

    def test_create_get(self):
        _run(self.store.create(self.ctx, "p1", name="finance", content="Always sum revenue."))
        tpl = _run(self.store.get(self.ctx, "p1"))
        self.assertEqual(tpl["name"], "finance")
        self.assertEqual(tpl["content"], "Always sum revenue.")

    def test_unknown_returns_none(self):
        self.assertIsNone(_run(self.store.get(self.ctx, "nope")))

    def test_tenant_scoped(self):
        _run(self.store.create(self.ctx, "p1", name="a", content="x"))
        other = RequestContext(source="api", organization_id="o2", project_id="p2")
        self.assertIsNone(_run(self.store.get(other, "p1")))

    def test_update_and_delete(self):
        _run(self.store.create(self.ctx, "p1", name="a", content="v1"))
        _run(self.store.update(self.ctx, "p1", content="v2"))
        self.assertEqual(_run(self.store.get(self.ctx, "p1"))["content"], "v2")
        _run(self.store.delete(self.ctx, "p1"))
        self.assertIsNone(_run(self.store.get(self.ctx, "p1")))

    def test_list(self):
        _run(self.store.create(self.ctx, "p1", name="a", content="x"))
        _run(self.store.create(self.ctx, "p2", name="b", content="y"))
        self.assertEqual(len(_run(self.store.list(self.ctx))), 2)
        names = {t["name"] for t in _run(self.store.list(self.ctx))}
        self.assertEqual(names, {"a", "b"})

    def test_tenant_scoped_list(self):
        _run(self.store.create(self.ctx, "p1", name="a", content="x"))
        other = RequestContext(source="api", organization_id="o2", project_id="p2")
        _run(self.store.create(other, "p2", name="b", content="y"))
        self.assertEqual([t["id"] for t in _run(self.store.list(self.ctx))], ["p1"])

    def test_delete_scoped_does_not_touch_other_org(self):
        _run(self.store.create(self.ctx, "p1", name="a", content="x"))
        other = RequestContext(source="api", organization_id="o2", project_id="p2")
        _run(self.store.delete(other, "p1"))
        self.assertIsNotNone(_run(self.store.get(self.ctx, "p1")))


if __name__ == "__main__":
    unittest.main()
