"""Prompt templates — OSS: up to 3 custom planner prompts, tenant-scoped."""
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from datahek.api.app import create_app
from datahek.defaults.container import build_app_container
from datahek.defaults.prompts import SqlitePromptStore, _run


def _store(tmp: str):
    return SqlitePromptStore(Path(tmp) / "prompts.db")


class TestPromptStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = _store(self._tmp.name)
        from datahek.kernel.context import RequestContext
        self.ctx = RequestContext(source="api")

    def tearDown(self):
        self._tmp.cleanup()

    def test_create_get(self):
        _run(self.store.create(self.ctx, "p1", name="finance", content="Always sum revenue."))
        tpl = _run(self.store.get(self.ctx, "p1"))
        self.assertEqual(tpl["name"], "finance")
        self.assertEqual(tpl["content"], "Always sum revenue.")

    def test_unknown_returns_none(self):
        self.assertIsNone(_run(self.store.get(self.ctx, "nope")))

    def test_tenant_scoped(self):
        from datahek.kernel.context import RequestContext

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


class TestPromptApi(unittest.TestCase):
    def setUp(self):
        container = build_app_container()
        self._tmp = tempfile.TemporaryDirectory()
        from datahek.contracts.prompts import PromptStore
        container.override(PromptStore, SqlitePromptStore(Path(self._tmp.name) / "p.db"))
        self.client = TestClient(create_app(container))

    def tearDown(self):
        self._tmp.cleanup()

    def test_crud(self):
        r = self.client.post("/prompts", json={"name": "finance", "content": "Always sum revenue."})
        self.assertEqual(r.status_code, 201, r.text)
        pid = r.json()["id"]
        r = self.client.get("/prompts")
        self.assertEqual(len(r.json()), 1)
        r = self.client.get(f"/prompts/{pid}")
        self.assertEqual(r.json()["name"], "finance")
        r = self.client.delete(f"/prompts/{pid}")
        self.assertEqual(r.status_code, 204)
        r = self.client.get(f"/prompts/{pid}")
        self.assertEqual(r.status_code, 404)

    def test_limit_three(self):
        for i in range(1, 4):
            r = self.client.post("/prompts", json={"name": f"p{i}", "content": "x"})
            self.assertEqual(r.status_code, 201, r.text)
        r = self.client.post("/prompts", json={"name": "p4", "content": "x"})
        self.assertEqual(r.status_code, 429, r.text)
        self.assertEqual(r.json()["code"], "RATE_LIMITED")
        self.assertEqual(r.json()["details"]["resource"], "prompt.templates")

    def test_ask_with_prompt_injects_content(self):
        from datahek.contracts.connections import Connection, ConnectionManager
        from datahek.contracts.models import ModelProvider, ModelResponse
        from datahek.contracts.prompts import PromptStore
        from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
        from datahek.defaults.connections import LocalConnectionManager
        from datahek.engine.executor import ProviderRegistry
        from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
        from datahek.engine.reasoner import ModelReasoner
        from datahek.contracts.reasoner import Reasoner

        class CapturingModel:
            def __init__(self):
                self.requests = []

            async def complete(self, request):
                self.requests.append(request)
                return ModelResponse(content='{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}')
            async def stream(self, request):
                yield "ok"

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
        container.override(PromptStore, SqlitePromptStore(Path(self._tmp.name) / "p2.db"))
        model = CapturingModel()
        container.override(ModelProvider, model)
        container.override(Reasoner, ModelReasoner(CapturingModel()))
        registry = ProviderRegistry()
        registry.register(FakeProvider())
        container.override(ProviderRegistry, registry)
        container.override(ConnectionManager, LocalConnectionManager([
            Connection(id="conn_1", name="ch1", provider="clickhouse", org_id="default", project_id="default"),
        ]))
        client = TestClient(create_app(container))

        pid = client.post("/prompts", json={"name": "finance", "content": "Always sum revenue."}).json()["id"]
        r = client.post("/ask", json={"question": "total revenue?", "connection_id": "conn_1", "prompt_id": pid})
        self.assertEqual(r.status_code, 200, r.text)
        planner_prompt = model.requests[0]["messages"][-1]["content"]
        self.assertIn("Always sum revenue", planner_prompt)


if __name__ == "__main__":
    unittest.main()