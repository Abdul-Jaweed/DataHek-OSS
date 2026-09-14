"""Rate limiting — sliding window + guardrail + executor mapping."""
import asyncio
import json
import unittest

from fastapi.testclient import TestClient

from datahek.api.app import create_app
from datahek.contracts.connections import Connection, ConnectionManager
from datahek.contracts.models import ModelProvider, ModelResponse
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
from datahek.defaults.connections import LocalConnectionManager
from datahek.defaults.container import build_app_container
from datahek.engine.executor import Engine, ProviderRegistry
from datahek.engine.plan import LogicalPlan, ReadNode
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext

PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}"""


class TestLocalRateLimiter(unittest.TestCase):
    def test_sliding_window(self):
        from datahek.defaults.rate_limit import LocalRateLimiter

        limiter = LocalRateLimiter()
        for _ in range(3):
            self.assertTrue(limiter.allow("u", limit=3, window_s=60))
        self.assertFalse(limiter.allow("u", limit=3, window_s=60))
        # another key unaffected
        self.assertTrue(limiter.allow("other", limit=3, window_s=60))

    def test_window_expiry(self):
        from unittest import mock
        from datahek.defaults.rate_limit import LocalRateLimiter

        limiter = LocalRateLimiter()
        with mock.patch("datahek.defaults.rate_limit.time.monotonic", return_value=0.0):
            self.assertTrue(limiter.allow("u", limit=1, window_s=10))
        with mock.patch("datahek.defaults.rate_limit.time.monotonic", return_value=11.0):
            self.assertTrue(limiter.allow("u", limit=1, window_s=10))


class _FakeModel:
    async def complete(self, request):
        return ModelResponse(content=PLAN)

    async def stream(self, request):
        yield "ok"


class _FakeProvider:
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


class TestRateLimitEnforcement(unittest.TestCase):
    def test_executor_raises_rate_limited(self):
        registry = ProviderRegistry()
        registry.register(_FakeProvider())
        engine = Engine(registry=registry, rate_limit=1)
        ctx = RequestContext(source="api", user_id="same-user")
        conn = Connection(id="c1", name="ch", provider="clickhouse", org_id="default", project_id="default")
        plan = LogicalPlan(nodes=[ReadNode(source="traces", columns=["service"], limit=5)])

        asyncio.run(engine.execute(ctx, plan, conn))
        from datahek.kernel.errors import DatahekError, ErrorCode

        with self.assertRaises(DatahekError) as cm:
            asyncio.run(engine.execute(ctx, plan, conn))
        self.assertEqual(cm.exception.code, ErrorCode.RATE_LIMITED)

    def test_api_returns_429_after_limit(self):
        c = build_app_container()
        c.override(ModelProvider, _FakeModel())
        registry = ProviderRegistry()
        registry.register(_FakeProvider())
        c.override(ProviderRegistry, registry)
        c.override(ConnectionManager, LocalConnectionManager([
            Connection(id="conn_1", name="ch1", provider="clickhouse", org_id="default", project_id="default")]))
        import os
        os.environ["DATAHEK_RATE_LIMIT_PER_MINUTE"] = "2"
        try:
            from datahek.engine.executor import Engine as _E
            c.override(_E, lambda: _E(registry=c.resolve(ProviderRegistry), rate_limit=2))
            client = TestClient(create_app(c))
            payload = {"question": "q", "connection_id": "conn_1"}
            r1 = client.post("/ask", json=payload)
            r2 = client.post("/ask", json=payload)
            r3 = client.post("/ask", json=payload)
        finally:
            os.environ.pop("DATAHEK_RATE_LIMIT_PER_MINUTE", None)
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r3.status_code, 429, r3.text)
        self.assertEqual(r3.json()["code"], "RATE_LIMITED")


if __name__ == "__main__":
    unittest.main()
