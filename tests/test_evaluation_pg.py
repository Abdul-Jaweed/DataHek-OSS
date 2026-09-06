"""Postgres evaluation store — mirrors the in-memory evaluation store behavior."""
import asyncio
import os
import unittest

from datahek.defaults.evaluation_pg import PostgresEvaluationStore
from datahek.defaults.pg import PgMetadata
from datahek.kernel.context import RequestContext

PG_URL = os.environ.get("DATAHEK_TEST_PG_URL") or "postgresql://datahek:datahek@127.0.0.1:55432/datahek"


def _run(coro):
    return asyncio.run(coro)


def _run_dict(run_id: str = "eval_run", *, execution: float = 1.0, status: str = "recorded") -> dict:
    return {
        "id": run_id,
        "org_id": "default",
        "project_id": "default",
        "scores": {
            "plan_validity": 1.0,
            "safety": 1.0,
            "execution": execution,
            "latency": 1.0,
        },
        "status": status,
    }


@unittest.skipUnless(os.environ.get("DATAHEK_TEST_PG_URL"), "postgres test container not running")
class TestPostgresEvaluationStore(unittest.TestCase):
    def setUp(self):
        self.pg = PgMetadata(url=PG_URL)

        async def setup():
            await self.pg.init_schema()
            conn = await self.pg.connect()
            try:
                conn.execute("TRUNCATE evaluation_runs")
            finally:
                conn.close()

        _run(setup())
        self.store = PostgresEvaluationStore(self.pg)
        self.ctx = RequestContext(source="api", user_id="alice")

    def test_record_and_list_round_trip(self):
        run = _run_dict("r1")
        _run(self.store.record(self.ctx, run))
        runs = _run(self.store.list(self.ctx))
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["id"], "r1")
        self.assertEqual(runs[0]["org_id"], "default")
        self.assertEqual(runs[0]["scores"]["execution"], 1.0)
        self.assertEqual(runs[0]["status"], "recorded")

    def test_record_generates_id(self):
        _run(self.store.record(self.ctx, _run_dict("r1")))
        conn = _run(self.pg.connect())
        try:
            row = conn.execute(
                "SELECT id FROM evaluation_runs WHERE org_id = %s",
                (self.ctx.organization_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertTrue(row[0].startswith("ent_"))
        self.assertGreater(len(row[0]), 4)

    def test_list_newest_first(self):
        _run(self.store.record(self.ctx, _run_dict("old", execution=0.0)))
        _run(self.store.record(self.ctx, _run_dict("new", execution=1.0)))
        runs = _run(self.store.list(self.ctx))
        self.assertEqual([r["id"] for r in runs], ["new", "old"])

    def test_aggregate_shape_and_pass_rate(self):
        _run(self.store.record(self.ctx, _run_dict("a", execution=1.0)))
        _run(self.store.record(self.ctx, _run_dict("b", execution=0.0)))
        agg = _run(self.store.aggregate(self.ctx))
        self.assertEqual(agg["total"], 2)
        self.assertEqual(agg["passed"], 1)
        self.assertEqual(agg["pass_rate"], 0.5)
        self.assertEqual(len(agg["runs"]), 2)

    def test_aggregate_empty(self):
        agg = _run(self.store.aggregate(self.ctx))
        self.assertEqual(agg["total"], 0)
        self.assertEqual(agg["passed"], 0)
        self.assertEqual(agg["pass_rate"], 0.0)
        self.assertEqual(agg["runs"], [])

    def test_tenant_scoping(self):
        _run(self.store.record(self.ctx, _run_dict("r1")))
        other = RequestContext(source="api", organization_id="other-org", project_id="other")
        _run(self.store.record(other, _run_dict("r2")))
        runs = _run(self.store.list(self.ctx))
        self.assertEqual([r["id"] for r in runs], ["r1"])
        agg = _run(self.store.aggregate(other))
        self.assertEqual(agg["total"], 1)
        self.assertEqual(agg["runs"][0]["id"], "r2")

    def test_persistence_across_instances(self):
        _run(self.store.record(self.ctx, _run_dict("r1")))
        store2 = PostgresEvaluationStore(self.pg)
        runs = _run(store2.list(self.ctx))
        self.assertEqual([r["id"] for r in runs], ["r1"])


if __name__ == "__main__":
    unittest.main()
