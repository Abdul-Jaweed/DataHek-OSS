"""Reasoner — natural-language explanation of query results."""
import asyncio
import unittest

from datahek.contracts.models import ModelProvider, ModelResponse
from datahek.engine.executor import ExecutionInfo, QueryResult
from datahek.engine.plan import LogicalPlan, ReadNode
from datahek.engine.reasoner import ModelReasoner, fallback_summary
from datahek.kernel.context import RequestContext


class _FakeModel(ModelProvider):
    def __init__(self, response: str, fail: bool = False):
        self._response = response
        self._fail = fail
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if self._fail:
            raise RuntimeError("model down")
        return ModelResponse(content=self._response)

    async def stream(self, request):
        yield self._response


def _result(rows=None):
    return QueryResult(
        columns=[{"name": "service", "type": "String"}, {"name": "n", "type": "UInt64"}],
        rows=rows if rows is not None else [("payment-api", 7), ("auth-service", 3)],
        row_count=len(rows) if rows is not None else 2,
        execution=ExecutionInfo(provider_id="clickhouse"),
    )


class TestFallbackSummary(unittest.TestCase):
    def test_summary_shape(self):
        text = fallback_summary(_result())
        self.assertIn("2 rows", text)
        self.assertIn("service", text)

    def test_empty_result(self):
        text = fallback_summary(_result(rows=[]))
        self.assertIn("No rows", text)


class TestModelReasoner(unittest.TestCase):
    def setUp(self):
        self.ctx = RequestContext(source="api")
        self.plan = LogicalPlan(nodes=[ReadNode(source="traces", columns=["service"], limit=10)])

    def test_explains_with_question_and_rows(self):
        model = _FakeModel("Errors are concentrated in payment-api (7).")
        reasoner = ModelReasoner(model)
        text = asyncio.run(reasoner.explain("which service errors?", _result(), self.plan, self.ctx))
        self.assertEqual(text, "Errors are concentrated in payment-api (7).")
        prompt = model.requests[0]["messages"][-1]["content"]
        self.assertIn("which service errors?", prompt)
        self.assertIn("payment-api", prompt)
        self.assertIn("traces", prompt)

    def test_model_failure_falls_back(self):
        reasoner = ModelReasoner(_FakeModel("", fail=True))
        text = asyncio.run(reasoner.explain("q", _result(), self.plan, self.ctx))
        self.assertIn("2 rows", text)

    def test_large_results_capped_in_prompt(self):
        model = _FakeModel("ok")
        reasoner = ModelReasoner(model, max_rows_in_prompt=3)
        rows = [(f"svc-{i}", i) for i in range(50)]
        asyncio.run(reasoner.explain("q", _result(rows=rows), self.plan, self.ctx))
        prompt = model.requests[0]["messages"][-1]["content"]
        self.assertIn("svc-0", prompt)
        self.assertNotIn("svc-40", prompt)


class TestAskIncludesExplanation(unittest.TestCase):
    def test_ask_returns_answer(self):
        from fastapi.testclient import TestClient

        from datahek.api.app import create_app
        from datahek.defaults.container import build_app_container
        from datahek.contracts.models import ModelResponse
        from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
        from datahek.engine.executor import ProviderRegistry
        from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta

        PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}"""

        class FakePlannerModel:
            async def complete(self, request):
                return ModelResponse(content=PLAN)
            async def stream(self, request):
                yield PLAN

        class FakeReasonerModel:
            async def complete(self, request):
                return ModelResponse(content="The top service is payment-api.")
            async def stream(self, request):
                yield "The top service is payment-api."

        class FakeProvider:
            provider_id = "clickhouse"
            capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)
            async def connect(self, connection): return object()
            async def introspect(self, ctx, connection, source):
                return SchemaCatalog(source=source, tables=[
                    TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")])])
            async def compile_and_execute(self, client, plan, ctx):
                return {"columns": [{"name": "service", "type": "String"}], "rows": [("payment-api",)]}
            async def close(self, client): pass

        container = build_app_container()
        from datahek.contracts.models import ModelProvider
        container.override(ModelProvider, FakePlannerModel())
        registry = ProviderRegistry()
        registry.register(FakeProvider())
        container.override(ProviderRegistry, registry)
        from datahek.engine.reasoner import ModelReasoner
        from datahek.contracts.reasoner import Reasoner
        container.override(Reasoner, ModelReasoner(FakeReasonerModel()))
        client = TestClient(create_app(container))

        r = client.post("/connections", json={"name": "ch", "provider": "clickhouse", "host": "h"})
        conn_id = r.json()["id"]
        r = client.post("/ask", json={"question": "top service?", "connection_id": conn_id})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["answer"], "The top service is payment-api.")
        self.assertEqual(body["rows"], [{"service": "payment-api"}])

    def test_conversation_records_answer(self):
        from fastapi.testclient import TestClient

        from datahek.api.app import create_app
        from datahek.defaults.container import build_app_container
        from datahek.contracts.models import ModelProvider, ModelResponse
        from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
        from datahek.engine.executor import ProviderRegistry
        from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
        from datahek.engine.reasoner import ModelReasoner
        from datahek.contracts.reasoner import Reasoner

        PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}"""

        class FakeModel:
            async def complete(self, request):
                return ModelResponse(content=PLAN)
            async def stream(self, request):
                yield PLAN

        class FakeProvider:
            provider_id = "clickhouse"
            capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)
            async def connect(self, connection): return object()
            async def introspect(self, ctx, connection, source):
                return SchemaCatalog(source=source, tables=[
                    TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")])])
            async def compile_and_execute(self, client, plan, ctx):
                return {"columns": [{"name": "service", "type": "String"}], "rows": [("payment-api",)]}
            async def close(self, client): pass

        container = build_app_container()
        container.override(ModelProvider, FakeModel())
        registry = ProviderRegistry()
        registry.register(FakeProvider())
        container.override(ProviderRegistry, registry)
        container.override(Reasoner, ModelReasoner(FakeModel()))
        client = TestClient(create_app(container))

        conv_id = client.post("/conversations", json={"title": "t"}).json()["id"]
        conn_id = client.post("/connections", json={"name": "ch", "provider": "clickhouse", "host": "h"}).json()["id"]
        r = client.post("/ask", json={"question": "q?", "connection_id": conn_id, "conversation_id": conv_id})
        self.assertEqual(r.status_code, 200)
        conv = client.get(f"/conversations/{conv_id}").json()
        self.assertEqual(conv["messages"][1]["role"], "assistant")
        self.assertEqual(conv["messages"][1]["message_type"], "result")


if __name__ == "__main__":
    unittest.main()