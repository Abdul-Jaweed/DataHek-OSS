"""Evaluation hooks — score every execution (validity, safety, latency)."""
import asyncio
import unittest

from datahek.contracts.evaluation import EvaluationStore
from datahek.defaults.evaluation import InMemoryEvaluationStore, LocalEvaluator, latency_score
from datahek.engine.executor import ExecutionInfo, QueryResult
from datahek.engine.plan import LogicalPlan, ReadNode, WriteNode
from datahek.kernel.context import RequestContext


class TestLatencyScore(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(latency_score(0.5), 1.0)
        self.assertEqual(latency_score(3), 0.8)
        self.assertEqual(latency_score(10), 0.5)
        self.assertEqual(latency_score(20), 0.2)


class TestLocalEvaluator(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryEvaluationStore()
        self.evaluator = LocalEvaluator(self.store)
        self.ctx = RequestContext(source="api", user_id="alice")

    def _result(self):
        return QueryResult(columns=[{"name": "a", "type": "Int32"}], rows=[(1,)],
                           row_count=1, execution=ExecutionInfo(provider_id="clickhouse", duration_ms=500))

    def test_successful_run_scored(self):
        plan = LogicalPlan(nodes=[ReadNode(source="t", columns=["a"])])
        asyncio.run(self.evaluator.on_execution_completed(
            self.ctx, plan=plan, result=self._result(), duration_ms=500, decision="ALLOW"))
        runs = asyncio.run(self.store.list(self.ctx))
        self.assertEqual(len(runs), 1)
        scores = runs[0]["scores"]
        self.assertEqual(scores["plan_validity"], 1.0)
        self.assertEqual(scores["safety"], 1.0)
        self.assertEqual(scores["execution"], 1.0)
        self.assertEqual(scores["latency"], 1.0)

    def test_denied_run_scored_zero_safety(self):
        plan = LogicalPlan(nodes=[WriteNode(source="t", operation="delete")])
        asyncio.run(self.evaluator.on_execution_completed(
            self.ctx, plan=plan, result=None, duration_ms=0, decision="DENY"))
        runs = asyncio.run(self.store.list(self.ctx))
        self.assertEqual(runs[0]["scores"]["safety"], 0.0)
        self.assertEqual(runs[0]["scores"]["execution"], 0.0)

    def test_failed_run_scored(self):
        plan = LogicalPlan(nodes=[ReadNode(source="t", columns=["a"])])
        asyncio.run(self.evaluator.on_execution_completed(
            self.ctx, plan=plan, result=None, duration_ms=100, decision="ALLOW", failed=True))
        self.assertEqual(asyncio.run(self.store.list(self.ctx))[0]["scores"]["execution"], 0.0)

    def test_aggregate_pass_rate(self):
        plan = LogicalPlan(nodes=[ReadNode(source="t", columns=["a"])])
        asyncio.run(self.evaluator.on_execution_completed(self.ctx, plan=plan, result=self._result(),
                                                          duration_ms=500, decision="ALLOW"))
        asyncio.run(self.evaluator.on_execution_completed(self.ctx, plan=plan, result=None,
                                                          duration_ms=0, decision="DENY"))
        agg = asyncio.run(self.store.aggregate(self.ctx))
        self.assertEqual(agg["total"], 2)
        self.assertEqual(agg["passed"], 1)
        self.assertEqual(agg["pass_rate"], 0.5)


class TestEngineEvaluationHook(unittest.TestCase):
    def test_engine_records_success_and_deny(self):
        from unittest import mock

        from datahek.contracts.connections import Connection
        from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
        from datahek.engine.executor import Engine, ProviderRegistry

        class FakeProvider:
            provider_id = "fake"
            capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=10)
            async def connect(self, connection): return object()
            async def compile_and_execute(self, client, plan, ctx):
                return {"columns": [{"name": "a", "type": "Int32"}], "rows": [(1,)]}
            async def close(self, client): pass

        registry = ProviderRegistry()
        registry.register(FakeProvider())
        store = InMemoryEvaluationStore()
        engine = Engine(registry, evaluation_hook=LocalEvaluator(store))
        ctx = RequestContext(source="api")
        conn = Connection(id="c1", name="c", provider="fake", org_id="default", project_id="default")

        ok = LogicalPlan(nodes=[ReadNode(source="t", columns=["a"])])
        asyncio.run(engine.execute(ctx, ok, conn))
        denied = LogicalPlan(nodes=[WriteNode(source="t", operation="delete")])
        with self.assertRaises(Exception):
            asyncio.run(engine.execute(ctx, denied, conn))

        runs = asyncio.run(store.list(ctx))
        self.assertEqual(len(runs), 2)
        by_safety = {r["scores"]["safety"] for r in runs}
        self.assertEqual(by_safety, {1.0, 0.0})


class TestEvaluationApi(unittest.TestCase):
    def test_evaluations_endpoint(self):
        from fastapi.testclient import TestClient

        from datahek.api.app import create_app
        from datahek.defaults.container import build_app_container
        from datahek.contracts.evaluation import EvaluationStore
        from datahek.defaults.evaluation import InMemoryEvaluationStore

        container = build_app_container()
        store = InMemoryEvaluationStore()
        container.override(EvaluationStore, store)
        client = TestClient(create_app(container))
        r = client.get("/evaluations")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total"], 0)
        self.assertIn("pass_rate", r.json())


if __name__ == "__main__":
    unittest.main()