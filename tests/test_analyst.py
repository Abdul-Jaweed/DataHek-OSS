"""Multi-step analyst — decomposition, per-step execution, synthesis."""
import json
import os
import unittest

from fastapi.testclient import TestClient

from datahek.api.app import create_app
from datahek.contracts.connections import Connection, ConnectionManager
from datahek.contracts.models import ModelProvider, ModelResponse
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
from datahek.defaults.connections import LocalConnectionManager
from datahek.defaults.container import build_app_container
from datahek.engine.executor import ProviderRegistry
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta

PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}"""


class _RoutingModel:
    """Routes by system prompt: decompose / plan / synthesis / verify."""

    def __init__(self, complex_question=True, steps=("count traces", "avg duration by service")):
        self._complex = complex_question
        self._steps = list(steps)
        self.plan_calls = 0

    async def complete(self, request):
        system = request["messages"][0]["content"]
        if "decompose" in system.lower():
            if self._complex:
                return ModelResponse(content=json.dumps({"complex": True, "steps": self._steps}))
            return ModelResponse(content=json.dumps({"complex": False, "steps": []}))
        if "You are an analyst" in system:
            return ModelResponse(content="Combined: 8 traces; auth-service is slowest at 675 ms.")
        if "verifier" in system.lower():
            return ModelResponse(content=json.dumps({"ok": True, "note": "ok"}))
        if "explain" in system.lower():
            return ModelResponse(content="There are 8 traces.")
        self.plan_calls += 1
        return ModelResponse(content=PLAN)

    async def stream(self, request):
        yield "ok"


class _Provider:
    provider_id = "clickhouse"
    capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)

    async def connect(self, connection):
        return object()

    async def introspect(self, ctx, connection, source):
        return SchemaCatalog(source=source, tables=[
            TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")])])

    async def compile_and_execute(self, client, plan, ctx):
        return {"columns": [{"name": "service", "type": "String"}], "rows": [("auth-service",)]}

    async def close(self, client):
        pass


def _client(model):
    c = build_app_container()
    c.override(ModelProvider, model)
    registry = ProviderRegistry()
    registry.register(_Provider())
    c.override(ProviderRegistry, registry)
    c.override(ConnectionManager, LocalConnectionManager([
        Connection(id="conn_1", name="ch1", provider="clickhouse", org_id="default", project_id="default")]))
    return TestClient(create_app(c))


class TestHeuristic(unittest.TestCase):
    def test_simple_question(self):
        from datahek.engine.analyst import MultiStepAnalyst
        self.assertFalse(MultiStepAnalyst.looks_complex("How many traces are there?"))

    def test_complex_question(self):
        from datahek.engine.analyst import MultiStepAnalyst
        self.assertTrue(MultiStepAnalyst.looks_complex("Compare average durations per service and explain why payment-api is slower"))

    def test_long_question(self):
        from datahek.engine.analyst import MultiStepAnalyst
        self.assertTrue(MultiStepAnalyst.looks_complex("x" * 130))


class TestDecompose(unittest.TestCase):
    def test_single_step_returns_empty(self):
        import asyncio
        from datahek.engine.analyst import MultiStepAnalyst

        analyst = MultiStepAnalyst(model=_RoutingModel(complex_question=False),
                                   planner=object(), engine=object(), reasoner=object())
        self.assertEqual(asyncio.run(analyst.decompose("q")), [])

    def test_steps_capped_at_max(self):
        import asyncio
        from datahek.engine.analyst import MultiStepAnalyst

        model = _RoutingModel(complex_question=True, steps=("a", "b", "c", "d", "e"))
        analyst = MultiStepAnalyst(model=model, planner=object(), engine=object(), reasoner=object(), max_steps=2)
        self.assertEqual(asyncio.run(analyst.decompose("q")), ["a", "b"])


class TestMultiStepApi(unittest.TestCase):
    def test_complex_question_runs_steps_and_synthesizes(self):
        model = _RoutingModel()
        client = _client(model)
        r = client.post("/ask", json={
            "question": "Compare average durations per service and explain why payment-api is slower",
            "connection_id": "conn_1"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(len(body["steps"]), 2)
        self.assertEqual(body["steps"][0]["question"], "count traces")
        self.assertIn("SELECT", body["steps"][0]["sql"])
        self.assertIn("Combined", body["answer"])
        self.assertEqual(model.plan_calls, 2)  # one plan per step

    def test_simple_question_single_step(self):
        model = _RoutingModel()
        client = _client(model)
        r = client.post("/ask", json={"question": "How many traces are there?", "connection_id": "conn_1"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json().get("steps"))
        self.assertEqual(model.plan_calls, 1)

    def test_stream_multi_step(self):
        model = _RoutingModel()
        client = _client(model)
        r = client.post("/ask/stream", json={
            "question": "Compare average durations per service and explain why payment-api is slower",
            "connection_id": "conn_1"})
        self.assertEqual(r.status_code, 200)
        events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
        types = [e["type"] for e in events]
        self.assertIn("steps", types)
        steps_ev = next(e for e in events if e["type"] == "steps")
        self.assertEqual(len(steps_ev["steps"]), 2)
        tokens = "".join(e["content"] for e in events if e["type"] == "token")
        self.assertIn("Combined", tokens)
        self.assertEqual(types[-1], "done")

    def test_env_disables_analyst(self):
        os.environ["DATAHEK_ANALYST"] = "off"
        try:
            model = _RoutingModel()
            client = _client(model)
            r = client.post("/ask", json={
                "question": "Compare durations per service and why", "connection_id": "conn_1"})
            self.assertIsNone(r.json().get("steps"))
        finally:
            os.environ.pop("DATAHEK_ANALYST", None)


if __name__ == "__main__":
    unittest.main()
