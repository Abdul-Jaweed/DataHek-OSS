"""Follow-up suggestions — opt-in LLM agent, fail-open."""
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
from datahek.engine.suggestions import FollowUpSuggester
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta

PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}"""


class _Model:
    def __init__(self, suggestions=("How about per status?", "Trend over time?", "Top by duration?")):
        self._suggestions = suggestions

    async def complete(self, request):
        system = request["messages"][0]["content"]
        if "suggest" in system.lower():
            return ModelResponse(content=json.dumps({"suggestions": list(self._suggestions)}))
        if "verifier" in system.lower():
            return ModelResponse(content=json.dumps({"ok": True, "note": "ok"}))
        if "explain" in system.lower():
            return ModelResponse(content="8 traces.")
        return ModelResponse(content=PLAN)

    async def stream(self, request):
        yield "ok"


class _BadSuggestModel(_Model):
    async def complete(self, request):
        system = request["messages"][0]["content"]
        if "suggest" in system.lower():
            raise RuntimeError("model down")
        return await super().complete(request)


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
        Connection(id="conn_1", name="ch1", provider="clickhouse",
                   org_id="default", project_id="default")]))
    return TestClient(create_app(c))


class TestSuggesterUnit(unittest.TestCase):
    def _result(self):
        from datahek.engine.executor import ExecutionInfo, QueryResult

        return QueryResult(columns=[{"name": "a", "type": "Int32"}], rows=[(1,)],
                           row_count=1, execution=ExecutionInfo(provider_id="clickhouse"))

    def test_parses_and_caps(self):
        suggester = FollowUpSuggester(_Model(suggestions=("a", "b", "c", "d")))
        out = asyncio.run(suggester.suggest("q", self._result(), object()))
        self.assertEqual(out, ["a", "b", "c"])

    def test_fails_open(self):
        suggester = FollowUpSuggester(_BadSuggestModel())
        self.assertEqual(asyncio.run(suggester.suggest("q", self._result(), object())), [])


class TestSuggestionsApi(unittest.TestCase):
    def test_disabled_by_default(self):
        client = _client(_Model())
        r = client.post("/ask", json={"question": "q", "connection_id": "conn_1"})
        self.assertIsNone(r.json().get("suggestions"))

    def test_enabled_returns_suggestions(self):
        os.environ["DATAHEK_SUGGESTIONS"] = "on"
        try:
            client = _client(_Model())
            r = client.post("/ask", json={"question": "q", "connection_id": "conn_1"})
            self.assertEqual(r.json()["suggestions"],
                             ["How about per status?", "Trend over time?", "Top by duration?"])
        finally:
            os.environ.pop("DATAHEK_SUGGESTIONS", None)

    def test_stream_emits_suggestions_event(self):
        os.environ["DATAHEK_SUGGESTIONS"] = "on"
        try:
            client = _client(_Model())
            r = client.post("/ask/stream", json={"question": "q", "connection_id": "conn_1"})
            events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
            sugg = next((e for e in events if e["type"] == "suggestions"), None)
            self.assertIsNotNone(sugg)
            self.assertEqual(len(sugg["items"]), 3)
        finally:
            os.environ.pop("DATAHEK_SUGGESTIONS", None)


if __name__ == "__main__":
    unittest.main()
