"""Evaluation dataset runner — curated offline regression cases + report."""
import asyncio
import unittest

from datahek.contracts.connections import Connection
from datahek.defaults.datasets import DatasetRunner, EvaluationCase, builtin_cases
from datahek.defaults.evaluation import InMemoryEvaluationStore
from datahek.engine.plan import Aggregate, LogicalPlan, ReadNode, WriteNode
from datahek.kernel.context import RequestContext


def _conn():
    return Connection(id="c1", name="ds", provider="dataset", org_id="default", project_id="default")


class TestBuiltinCases(unittest.TestCase):
    def test_three_curated_cases(self):
        cases = builtin_cases()
        names = {c.name for c in cases}
        self.assertEqual(len(cases), 3)
        self.assertIn("analytics.top_services", names)
        self.assertIn("safety.drop_attempt", names)
        self.assertIn("unknown_table", names)

    def test_drop_attempt_expects_denied(self):
        case = next(c for c in builtin_cases() if c.name == "safety.drop_attempt")
        self.assertEqual(case.expect, "denied")
        self.assertFalse(case.plan.read_only)


class TestDatasetRunner(unittest.TestCase):
    def setUp(self):
        self.runner = DatasetRunner()
        self.ctx = RequestContext(source="api")

    def test_all_cases_pass(self):
        report = asyncio.run(self.runner.run(self.ctx, _conn()))
        self.assertEqual(report["total"], 3)
        self.assertEqual(report["passed"], 3)
        self.assertEqual(report["pass_rate"], 1.0)
        for case in report["cases"]:
            self.assertTrue(case["passed"], case["name"])
            self.assertIn("scores", case)

    def test_scores_recorded(self):
        report = asyncio.run(self.runner.run(self.ctx, _conn()))
        by_name = {c["name"]: c for c in report["cases"]}
        self.assertEqual(by_name["analytics.top_services"]["scores"]["execution"], 1.0)
        self.assertEqual(by_name["analytics.top_services"]["scores"]["safety"], 1.0)
        self.assertEqual(by_name["safety.drop_attempt"]["scores"]["safety"], 0.0)

    def test_misbehaving_case_fails(self):
        bad_case = EvaluationCase(
            name="should_have_been_denied",
            plan=LogicalPlan(nodes=[ReadNode(source="traces", columns=["service"], limit=5)]),
            expect="denied",
        )
        report = asyncio.run(self.runner.run(self.ctx, _conn(), cases=[bad_case]))
        self.assertEqual(report["passed"], 0)
        self.assertEqual(report["pass_rate"], 0.0)
        self.assertFalse(report["cases"][0]["passed"])

    def test_store_records_runs(self):
        store = InMemoryEvaluationStore()
        runner = DatasetRunner(store=store)
        asyncio.run(runner.run(self.ctx, _conn()))
        runs = asyncio.run(store.list(self.ctx))
        self.assertEqual(len(runs), 3)


class TestDatasetApi(unittest.TestCase):
    def test_run_endpoint(self):
        from fastapi.testclient import TestClient

        from datahek.api.app import create_app
        from datahek.defaults.container import build_app_container
        from datahek.defaults.datasets import DatasetRunner
        from datahek.contracts.evaluation import EvaluationStore

        container = build_app_container()
        store = InMemoryEvaluationStore()
        container.override(EvaluationStore, store)
        container.override(EvaluationStore, store)
        client = TestClient(create_app(container))
        r = client.post("/evaluations/run")
        self.assertEqual(r.status_code, 200, r.text)
        report = r.json()
        self.assertEqual(report["total"], 3)
        self.assertEqual(report["pass_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()