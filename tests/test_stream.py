"""SSE streaming — /ask/stream streams explanation tokens + result events."""
import json
import unittest

from fastapi.testclient import TestClient

from datahek.api.app import create_app
from datahek.defaults.container import build_app_container
from datahek.contracts.connections import Connection, ConnectionManager
from datahek.contracts.models import ModelProvider, ModelResponse
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
from datahek.defaults.connections import LocalConnectionManager
from datahek.engine.executor import ProviderRegistry
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext


PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}"""


class _FakePlannerModel:
    async def complete(self, request):
        return ModelResponse(content=PLAN)
    async def stream(self, request):
        yield "The "
        yield "top "
        yield "service"


class _FakeReasonerModel:
    async def complete(self, request):
        return ModelResponse(content="The top service.")
    async def stream(self, request):
        yield "The "
        yield "top "
        yield "service."


class _FakeProvider:
    provider_id = "clickhouse"
    capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)
    async def connect(self, connection): return object()
    async def introspect(self, ctx, connection, source):
        return SchemaCatalog(source=source, tables=[
            TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")])])
    async def compile_and_execute(self, client, plan, ctx):
        return {"columns": [{"name": "service", "type": "String"}], "rows": [("payment-api",)]}
    async def close(self, client): pass


def _app():
    from datahek.contracts.models import ModelProvider
    from datahek.contracts.reasoner import Reasoner
    from datahek.engine.reasoner import ModelReasoner

    c = build_app_container()
    c.override(ModelProvider, _FakePlannerModel())
    c.override(Reasoner, ModelReasoner(_FakeReasonerModel()))
    registry = ProviderRegistry()
    registry.register(_FakeProvider())
    c.override(ProviderRegistry, registry)
    c.override(ConnectionManager, LocalConnectionManager([
        Connection(id="conn_1", name="ch1", provider="clickhouse", org_id="default", project_id="default"),
    ]))
    return create_app(c)


def _events(text: str):
    out = []
    for line in text.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


class TestAskStream(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_app())

    def test_streams_tokens_rows_and_done(self):
        r = self.client.post("/ask/stream", json={"question": "top service?", "connection_id": "conn_1"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("text/event-stream", r.headers["content-type"])
        self.assertIn("X-Conversation-ID", r.headers)
        events = _events(r.text)
        types = [e["type"] for e in events]
        self.assertEqual(types[0], "start")
        self.assertIn("token", types)
        self.assertEqual(types[-2], "rows")
        self.assertEqual(types[-1], "done")
        tokens = "".join(e["content"] for e in events if e["type"] == "token")
        self.assertEqual(tokens, "The top service.")
        rows_evt = next(e for e in events if e["type"] == "rows")
        self.assertEqual(rows_evt["rows"], [{"service": "payment-api"}])

    def test_clarification_streamed(self):
        from datahek.contracts.models import ModelProvider

        class ClarifyModel:
            async def complete(self, request):
                return ModelResponse(content='{"nodes": [], "clarification": "Which table?"}')
            async def stream(self, request):
                yield ""

        c = build_app_container()
        c.override(ModelProvider, ClarifyModel())
        registry = ProviderRegistry()
        registry.register(_FakeProvider())
        c.override(ProviderRegistry, registry)
        c.override(ConnectionManager, LocalConnectionManager([
            Connection(id="conn_1", name="ch1", provider="clickhouse", org_id="default", project_id="default"),
        ]))
        client = TestClient(create_app(c))
        r = client.post("/ask/stream", json={"question": "q", "connection_id": "conn_1"})
        self.assertEqual(r.status_code, 200)
        events = _events(r.text)
        self.assertEqual(events[0]["type"], "clarification")
        self.assertEqual(events[0]["text"], "Which table?")

    def test_unknown_connection_is_json_error(self):
        r = self.client.post("/ask/stream", json={"question": "q", "connection_id": "nope"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["code"], "CONNECTION_NOT_FOUND")

    def test_records_conversation_once(self):
        r = self.client.post("/conversations", json={"title": "t"})
        conv_id = r.json()["id"]
        r = self.client.post("/ask/stream", json={
            "question": "top service?", "connection_id": "conn_1", "conversation_id": conv_id})
        self.assertEqual(r.status_code, 200)
        conv = self.client.get(f"/conversations/{conv_id}").json()
        roles = [m["role"] for m in conv["messages"]]
        self.assertEqual(roles, ["user", "assistant"])


class TestStreamingReasoner(unittest.TestCase):
    def test_stream_yields_tokens(self):
        import asyncio

        from datahek.engine.reasoner import ModelReasoner
        from datahek.engine.executor import ExecutionInfo, QueryResult
        from datahek.engine.plan import LogicalPlan, ReadNode

        reasoner = ModelReasoner(_FakeReasonerModel())
        result = QueryResult(columns=[{"name": "a", "type": "Int32"}], rows=[(1,)],
                             row_count=1, execution=ExecutionInfo(provider_id="clickhouse"))

        async def run():
            return "".join([c async for c in reasoner.stream_explanation(
                "q", result, LogicalPlan(nodes=[ReadNode(source="t", columns=["a"])]),
                RequestContext(source="api"))])

        self.assertEqual(asyncio.run(run()), "The top service.")

    def test_stream_failure_falls_back(self):
        import asyncio

        from datahek.engine.reasoner import ModelReasoner, fallback_summary
        from datahek.engine.executor import ExecutionInfo, QueryResult
        from datahek.engine.plan import LogicalPlan, ReadNode

        class FailingModel:
            async def stream(self, request):
                raise RuntimeError("down")
            async def complete(self, request):
                raise RuntimeError("down")

        reasoner = ModelReasoner(FailingModel())
        result = QueryResult(columns=[{"name": "a", "type": "Int32"}], rows=[(1,)],
                             row_count=1, execution=ExecutionInfo(provider_id="clickhouse"))

        async def run():
            return "".join([c async for c in reasoner.stream_explanation(
                "q", result, LogicalPlan(nodes=[ReadNode(source="t", columns=["a"])]),
                RequestContext(source="api"))])

        self.assertEqual(asyncio.run(run()), fallback_summary(result))


if __name__ == "__main__":
    unittest.main()