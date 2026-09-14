"""Conversation context — follow-up questions resolve against prior turns."""
import json
import unittest

from fastapi.testclient import TestClient

from datahek.api.app import create_app
from datahek.contracts.connections import Connection, ConnectionManager
from datahek.contracts.models import ModelProvider, ModelResponse
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
from datahek.defaults.connections import LocalConnectionManager
from datahek.defaults.container import build_app_container
from datahek.engine.executor import ProviderRegistry
from datahek.engine.planner import _format_history
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta

PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}"""


class _CapturingModel:
    def __init__(self):
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        system = request["messages"][0]["content"]
        if "verifier" in system.lower():
            return ModelResponse(content=json.dumps({"ok": True, "note": "ok"}))
        if "explain" in system.lower():
            return ModelResponse(content="There are 8 traces.")
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
        return {"columns": [{"name": "service", "type": "String"}], "rows": [("x",)]}

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


def _planner_prompts(model) -> list[str]:
    """User messages of plan requests (planner system prompt marker)."""
    out = []
    for req in model.requests:
        system = req["messages"][0]["content"]
        if "planner of a read-only" in system:
            out.append(req["messages"][1]["content"])
    return out


class TestFormatHistory(unittest.TestCase):
    def test_formats_roles(self):
        block = _format_history([
            {"role": "user", "content": "How many traces?"},
            {"role": "assistant", "content": "There are 8."},
        ])
        self.assertIn("User: How many traces?", block)
        self.assertIn("Assistant: There are 8.", block)

    def test_truncates_long_messages(self):
        block = _format_history([{"role": "assistant", "content": "x" * 1000}], per_message=50)
        self.assertLess(len(block), 100)

    def test_caps_total(self):
        history = [{"role": "user", "content": "q" * 300} for _ in range(20)]
        block = _format_history(history, max_chars=500)
        self.assertLessEqual(len(block), 600)

    def test_empty(self):
        self.assertEqual(_format_history(None), "")
        self.assertEqual(_format_history([]), "")


class TestConversationContext(unittest.TestCase):
    def test_follow_up_includes_history(self):
        model = _CapturingModel()
        client = _client(model)
        conv = client.post("/conversations", json={"title": "flow"}).json()

        r1 = client.post("/ask", json={"question": "How many traces are there?",
                                       "connection_id": "conn_1", "conversation_id": conv["id"]})
        self.assertEqual(r1.status_code, 200, r1.text)

        r2 = client.post("/ask", json={"question": "and what is the average duration?",
                                       "connection_id": "conn_1", "conversation_id": conv["id"]})
        self.assertEqual(r2.status_code, 200, r2.text)

        prompts = _planner_prompts(model)
        self.assertEqual(len(prompts), 2)
        self.assertNotIn("Conversation so far", prompts[0])
        self.assertIn("Conversation so far", prompts[1])
        self.assertIn("How many traces are there?", prompts[1])

    def test_no_conversation_no_history(self):
        model = _CapturingModel()
        client = _client(model)
        client.post("/ask", json={"question": "q1", "connection_id": "conn_1"})
        client.post("/ask", json={"question": "q2", "connection_id": "conn_1"})
        for prompt in _planner_prompts(model):
            self.assertNotIn("Conversation so far", prompt)

    def test_stream_follow_up_includes_history(self):
        model = _CapturingModel()
        client = _client(model)
        conv = client.post("/conversations", json={"title": "flow"}).json()
        client.post("/ask/stream", json={"question": "How many traces?",
                                         "connection_id": "conn_1", "conversation_id": conv["id"]})
        client.post("/ask/stream", json={"question": "and per service?",
                                         "connection_id": "conn_1", "conversation_id": conv["id"]})
        prompts = _planner_prompts(model)
        self.assertIn("Conversation so far", prompts[-1])


if __name__ == "__main__":
    unittest.main()
