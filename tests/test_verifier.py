"""Verifier — independent post-execution answer checking."""
import asyncio
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


class _PlanningModel:
    """Returns the plan for planning; a verify verdict for the verifier prompt."""

    def __init__(self, verdict_content=json.dumps({"ok": True, "note": "looks right"})):
        self._verdict = verdict_content

    async def complete(self, request):
        system = request["messages"][0]["content"]
        if "verifier" in system.lower():
            return ModelResponse(content=self._verdict)
        return ModelResponse(content=PLAN)

    async def stream(self, request):
        yield "ok"


class _BoomVerifyModel(_PlanningModel):
    async def complete(self, request):
        system = request["messages"][0]["content"]
        if "verifier" in system.lower():
            raise RuntimeError("verify model down")
        return ModelResponse(content=PLAN)


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


def _client(model):
    c = build_app_container()
    c.override(ModelProvider, model)
    registry = ProviderRegistry()
    registry.register(_FakeProvider())
    c.override(ProviderRegistry, registry)
    c.override(ConnectionManager, LocalConnectionManager([
        Connection(id="conn_1", name="ch1", provider="clickhouse", org_id="default", project_id="default")]))
    return TestClient(create_app(c))


class TestModelVerifier(unittest.TestCase):
    def _result(self):
        from datahek.engine.executor import ExecutionInfo, QueryResult

        return QueryResult(columns=[{"name": "a", "type": "Int32"}], rows=[(1,)], row_count=1,
                           execution=ExecutionInfo(provider_id="clickhouse"))

    def test_verdict_parsed(self):
        from datahek.engine.verifier import ModelVerifier

        v = ModelVerifier(_PlanningModel(json.dumps({"ok": False, "note": "missing rows"})))
        verdict = asyncio.run(v.verify("q", self._result(), object()))
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["note"], "missing rows")

    def test_fail_open_on_model_error(self):
        from datahek.engine.verifier import ModelVerifier

        v = ModelVerifier(_BoomVerifyModel())
        verdict = asyncio.run(v.verify("q", self._result(), object()))
        self.assertTrue(verdict["ok"])
        self.assertIn("unavailable", verdict["note"])


class TestVerifierApi(unittest.TestCase):
    def test_ask_includes_verification(self):
        client = _client(_PlanningModel())
        r = client.post("/ask", json={"question": "q", "connection_id": "conn_1"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["verification"]["ok"], True)

    def test_stream_emits_verification_event(self):
        client = _client(_PlanningModel())
        r = client.post("/ask/stream", json={"question": "q", "connection_id": "conn_1"})
        self.assertEqual(r.status_code, 200)
        events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
        self.assertTrue(any(e["type"] == "verification" for e in events))

    def test_disabled_by_env(self):
        os.environ["DATAHEK_VERIFIER"] = "off"
        try:
            client = _client(_PlanningModel())
            r = client.post("/ask", json={"question": "q", "connection_id": "conn_1"})
            self.assertIsNone(r.json()["verification"])
        finally:
            os.environ.pop("DATAHEK_VERIFIER", None)


if __name__ == "__main__":
    unittest.main()
