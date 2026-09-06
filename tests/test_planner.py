"""Agent planner — question → schema-grounded LogicalPlan or clarification."""
import asyncio
import json
import unittest
from unittest import mock

from datahek.contracts.connections import Connection
from datahek.contracts.models import ModelProvider, ModelRequest, ModelResponse
from datahek.engine.planner import PlanResult, Planner, build_schema_summary
from datahek.engine.schema import _CatalogEntry, ColumnMeta, SchemaCatalog, SchemaService, TableMeta
from datahek.kernel.context import RequestContext


def _catalog():
    return SchemaCatalog(
        source="c1:default",
        tables=[
            TableMeta(name="traces", columns=[
                ColumnMeta(name="service", data_type="String"),
                ColumnMeta(name="duration_ms", data_type="UInt32"),
                ColumnMeta(name="status", data_type="String"),
            ]),
            TableMeta(name="metrics", columns=[ColumnMeta(name="name", data_type="String")]),
        ],
    )


class _FakeModel(ModelProvider):
    def __init__(self, response: str):
        self._response = response
        self.requests: list[ModelRequest] = []
        self.attempts = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.attempts += 1
        self.requests.append(request)
        return ModelResponse(content=self._response)

    async def stream(self, request: ModelRequest):
        yield self._response


def _plan_json():
    return {
        "nodes": [
            {
                "type": "ReadNode",
                "source": "traces",
                "columns": ["service"],
                "filter": "status = 'error'",
                "group_by": ["service"],
                "aggregates": [{"function": "count", "column": "*", "alias": "n"}],
                "order_by": ["n DESC"],
                "limit": 10,
            }
        ]
    }


def _service():
    import time

    s = SchemaService()
    s._entries["c1:default"] = _CatalogEntry(catalog=_catalog(), fetched_at=time.time())
    return s


class _FakeProvider:
    provider_id = "clickhouse"

    class capabilities:
        dialect = "clickhouse"


class TestBuildSchemaSummary(unittest.TestCase):
    def test_summary_contains_tables_and_columns(self):
        summary = build_schema_summary(_catalog())
        self.assertIn("traces", summary)
        self.assertIn("duration_ms", summary)
        self.assertIn("metrics", summary)

    def test_summary_has_no_llm_prompt_noise(self):
        summary = build_schema_summary(_catalog())
        self.assertNotIn("system prompt", summary.lower())


class TestPlanner(unittest.TestCase):
    def setUp(self):
        self.ctx = RequestContext(source="api")
        self.conn = Connection(id="c1", name="ch", provider="clickhouse", org_id="default", project_id="default")
        self.service = _service()
        self.provider = _FakeProvider()

    def _planner(self, model):
        return Planner(model=model, schema_service=self.service)

    def test_returns_validated_plan(self):
        model = _FakeModel(json.dumps(_plan_json()))
        result = asyncio.run(self._planner(model).plan("error count by service", self.ctx, self.conn, self.provider))
        self.assertIsNotNone(result.plan)
        self.assertTrue(result.plan.read_only)
        self.assertEqual(result.plan.nodes[0].source, "traces")
        self.assertEqual(result.clarification, None)
        self.assertEqual(result.sources_used, ["traces"])

    def test_prompt_grounds_on_schema(self):
        model = _FakeModel(json.dumps(_plan_json()))
        asyncio.run(self._planner(model).plan("question", self.ctx, self.conn, self.provider))
        prompt = model.requests[0]["messages"][-1]["content"]
        self.assertIn("traces", prompt)
        self.assertIn("duration_ms", prompt)

    def test_unknown_table_retries_then_clarifies(self):
        plan = {"nodes": [{"type": "ReadNode", "source": "ghost", "columns": ["x"]}]}
        model = _FakeModel(json.dumps(plan))
        result = asyncio.run(self._planner(model).plan("q", self.ctx, self.conn, self.provider))
        self.assertIsNone(result.plan)
        self.assertIsNotNone(result.clarification)
        self.assertGreater(model.attempts, 1)  # retried with feedback

    def test_clarification_when_no_schema_match(self):
        model = _FakeModel(json.dumps({"nodes": [], "clarification": "Which table do you mean?"}))
        result = asyncio.run(self._planner(model).plan("q", self.ctx, self.conn, self.provider))
        self.assertIsNone(result.plan)
        self.assertEqual(result.clarification, "Which table do you mean?")

    def test_malformed_json_becomes_clarification(self):
        model = _FakeModel("not json at all")
        result = asyncio.run(self._planner(model).plan("q", self.ctx, self.conn, self.provider))
        self.assertIsNone(result.plan)
        self.assertIsNotNone(result.clarification)

    def test_plan_result_shapes(self):
        result = PlanResult(plan=None, clarification="hi", confidence=0.5, sources_used=[])
        self.assertEqual(result.confidence, 0.5)
        self.assertEqual(result.clarification, "hi")


class TestPlannerModelFailures(unittest.TestCase):
    def _plan_env(self):
        import time

        from datahek.contracts.connections import Connection
        from datahek.contracts.models import ModelProviderError
        from datahek.engine.schema import _CatalogEntry
        from datahek.kernel.context import RequestContext

        catalog = SchemaCatalog(source="c1:default", tables=[
            TableMeta(name="traces", columns=[ColumnMeta(name="a", data_type="Int32")])])
        service = SchemaService()
        service._entries["c1:default"] = _CatalogEntry(catalog=catalog, fetched_at=time.time())
        conn = Connection(id="c1", name="ch", provider="clickhouse", org_id="default", project_id="default")
        provider = type("P", (), {"provider_id": "clickhouse"})()
        return service, conn, provider

    def test_rate_limit_becomes_typed_error(self):
        from datahek.contracts.models import ModelProviderError
        from datahek.kernel.errors import DatahekError, ErrorCode

        class FailingModel:
            async def complete(self, request):
                raise ModelProviderError("rate limited", status_code=429)
            async def stream(self, request):
                yield ""

        service, conn, provider = self._plan_env()
        planner = Planner(model=FailingModel(), schema_service=service)
        with self.assertRaises(DatahekError) as cm:
            asyncio.run(planner.plan("q", RequestContext(source="api"), conn, provider))
        self.assertEqual(cm.exception.code, ErrorCode.RATE_LIMITED)

    def test_other_http_error_becomes_model_unavailable(self):
        from datahek.contracts.models import ModelProviderError
        from datahek.kernel.errors import DatahekError, ErrorCode

        class FailingModel:
            async def complete(self, request):
                raise ModelProviderError("server error", status_code=502)
            async def stream(self, request):
                yield ""

        service, conn, provider = self._plan_env()
        planner = Planner(model=FailingModel(), schema_service=service)
        with self.assertRaises(DatahekError) as cm:
            asyncio.run(planner.plan("q", RequestContext(source="api"), conn, provider))
        self.assertEqual(cm.exception.code, ErrorCode.MODEL_UNAVAILABLE)


class TestModelProviderErrorConversion(unittest.TestCase):
    def test_httpx_error_converted(self):
        import httpx

        from datahek.defaults.models import OpenAICompatibleModelProvider
        from datahek.contracts.models import ModelProviderError

        p = OpenAICompatibleModelProvider()
        err = httpx.HTTPStatusError("429", request=httpx.Request("POST", "http://x"),
                                    response=httpx.Response(429))
        with mock.patch.object(p, "_post", side_effect=err):
            with self.assertRaises(ModelProviderError) as cm:
                asyncio.run(p.complete({"messages": [{"role": "user", "content": "hi"}]}))
        self.assertEqual(cm.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()