"""Semantic layer — metric CRUD, planner prompt injection, API."""
import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from datahek.api.app import create_app
from datahek.contracts.connections import Connection, ConnectionManager
from datahek.contracts.models import ModelProvider, ModelResponse
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
from datahek.contracts.semantics import Metric
from datahek.defaults.connections import LocalConnectionManager
from datahek.defaults.container import build_app_container
from datahek.engine.executor import ProviderRegistry
from datahek.engine.planner import _format_metrics
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext

PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}"""


class TestStore(unittest.TestCase):
    def test_crud_roundtrip(self):
        import asyncio
        from datahek.defaults.semantics import SqliteSemanticStore

        with tempfile.TemporaryDirectory() as d:
            store = SqliteSemanticStore(f"{d}/m.db")
            ctx = RequestContext(source="api")
            metric = Metric(id="m1", name="revenue", table="orders", aggregate="sum",
                            column="amount", description="total sales")
            asyncio.run(store.create(ctx, metric))
            got = asyncio.run(store.get(ctx, "m1"))
            self.assertEqual(got["name"], "revenue")
            self.assertEqual(got["aggregate"], "sum")

            asyncio.run(store.update(ctx, "m1", {"description": "gross revenue"}))
            self.assertEqual(asyncio.run(store.get(ctx, "m1"))["description"], "gross revenue")

            self.assertEqual(len(asyncio.run(store.list(ctx))), 1)
            asyncio.run(store.delete(ctx, "m1"))
            self.assertIsNone(asyncio.run(store.get(ctx, "m1")))


class TestFormatMetrics(unittest.TestCase):
    def test_renders_definitions(self):
        block = _format_metrics([
            {"name": "revenue", "table": "orders", "aggregate": "sum",
             "column": "amount", "filter": None, "description": "total sales"},
        ], "what was revenue?")
        self.assertIn("revenue: sum(amount) on orders", block)
        self.assertIn('"total sales"', block)

    def test_filter_included(self):
        block = _format_metrics([
            {"name": "error_rate", "table": "traces", "aggregate": "count",
             "column": "*", "filter": "status = 'error'", "description": ""},
        ], "errors?")
        self.assertIn("count(*) WHERE status = 'error'", block)

    def test_empty(self):
        self.assertEqual(_format_metrics([], "q"), "")


class _CapturingModel:
    def __init__(self):
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        system = request["messages"][0]["content"]
        if "verifier" in system.lower():
            return ModelResponse(content=json.dumps({"ok": True, "note": "ok"}))
        if "explain" in system.lower():
            return ModelResponse(content="ok")
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


def _client(model, db_path):
    os.environ["DATAHEK_DB_PATH"] = db_path
    try:
        c = build_app_container()
        c.override(ModelProvider, model)
        registry = ProviderRegistry()
        registry.register(_Provider())
        c.override(ProviderRegistry, registry)
        c.override(ConnectionManager, LocalConnectionManager([
            Connection(id="conn_1", name="ch1", provider="clickhouse", org_id="default", project_id="default")]))
        return TestClient(create_app(c))
    finally:
        os.environ.pop("DATAHEK_DB_PATH", None)


class TestMetricApi(unittest.TestCase):
    def test_crud_and_validation(self):
        with tempfile.TemporaryDirectory() as d:
            client = _client(_CapturingModel(), f"{d}/db.sqlite")
            r = client.post("/metrics", json={
                "name": "revenue", "table": "orders", "aggregate": "sum",
                "column": "amount", "description": "total sales"})
            self.assertEqual(r.status_code, 201, r.text)
            mid = r.json()["id"]

            r = client.get("/metrics")
            self.assertEqual(len(r.json()), 1)
            self.assertEqual(r.json()[0]["name"], "revenue")

            r = client.put(f"/metrics/{mid}", json={
                "name": "revenue", "table": "orders", "aggregate": "sum",
                "column": "amount", "description": "updated"})
            self.assertEqual(r.json()["description"], "updated")

            r = client.post("/metrics", json={"name": "bad", "table": "t", "aggregate": "median"})
            self.assertEqual(r.status_code, 422)

            self.assertEqual(client.delete(f"/metrics/{mid}").status_code, 204)
            self.assertEqual(client.delete(f"/metrics/{mid}").status_code, 404)

    def test_planner_prompt_receives_metrics(self):
        with tempfile.TemporaryDirectory() as d:
            model = _CapturingModel()
            client = _client(model, f"{d}/db.sqlite")
            client.post("/metrics", json={
                "name": "revenue", "table": "orders", "aggregate": "sum",
                "column": "amount", "description": "total sales"})
            client.post("/ask", json={"question": "what was the revenue?", "connection_id": "conn_1"})

            plan_prompts = [
                req["messages"][1]["content"]
                for req in model.requests
                if "planner of a read-only" in req["messages"][0]["content"]
            ]
            self.assertTrue(any("Metric definitions" in p for p in plan_prompts))
            self.assertTrue(any("revenue: sum(amount) on orders" in p for p in plan_prompts))


if __name__ == "__main__":
    unittest.main()
