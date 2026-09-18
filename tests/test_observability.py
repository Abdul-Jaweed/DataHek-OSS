"""Observability — Prometheus /metrics and structured JSON logging."""
import io
import json
import logging
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


class TestLocalMetrics(unittest.TestCase):
    def test_counter_and_observation_render(self):
        from datahek.defaults.metrics import LocalMetrics

        m = LocalMetrics()
        m.inc("datahek_requests_total", endpoint="/ask", status=200)
        m.inc("datahek_requests_total", endpoint="/ask", status=200)
        m.observe("datahek_request_duration_seconds", 0.5, endpoint="/ask")
        out = m.render()
        self.assertIn('# TYPE datahek_requests_total counter', out)
        self.assertIn('datahek_requests_total{endpoint="/ask",status="200"} 2', out)
        self.assertIn('datahek_request_duration_seconds_sum{endpoint="/ask"} 0.5', out)
        self.assertIn('datahek_request_duration_seconds_count{endpoint="/ask"} 1', out)
        self.assertIn("# TYPE datahek_uptime_seconds gauge", out)


class TestJsonLogging(unittest.TestCase):
    def test_json_formatter_outputs_parseable_line(self):
        from datahek.defaults.log_setup import JsonFormatter

        record = logging.LogRecord("datahek.test", logging.WARNING, __file__, 1,
                                   "something happened", None, None)
        line = JsonFormatter().format(record)
        payload = json.loads(line)
        self.assertEqual(payload["level"], "WARNING")
        self.assertEqual(payload["logger"], "datahek.test")
        self.assertEqual(payload["message"], "something happened")

    def test_configure_logging_switches_by_env(self):
        from datahek.defaults.log_setup import JsonFormatter, configure_logging

        os.environ["DATAHEK_LOG_FORMAT"] = "json"
        try:
            configure_logging()
            root = logging.getLogger()
            self.assertTrue(isinstance(root.handlers[0].formatter, JsonFormatter))
        finally:
            os.environ.pop("DATAHEK_LOG_FORMAT", None)
            logging.getLogger().handlers = [logging.StreamHandler()]


class _FakeModel:
    async def complete(self, request):
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


def _client():
    c = build_app_container()
    c.override(ModelProvider, _FakeModel())
    registry = ProviderRegistry()
    registry.register(_Provider())
    c.override(ProviderRegistry, registry)
    c.override(ConnectionManager, LocalConnectionManager([
        Connection(id="conn_1", name="ch1", provider="clickhouse", org_id="default", project_id="default")]))
    return TestClient(create_app(c))


class TestMetricsEndpoint(unittest.TestCase):
    def test_metrics_served_and_counted(self):
        client = _client()
        client.get("/health")
        client.post("/ask", json={"question": "q", "connection_id": "conn_1"})

        r = client.get("/metrics")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/plain", r.headers["content-type"])
        body = r.text
        self.assertIn('datahek_requests_total{endpoint="/ask",status="200"}', body)
        self.assertIn('datahek_ask_results_total{outcome="ok"}', body)
        self.assertIn("datahek_rows_returned_total", body)

    def test_error_outcomes_counted(self):
        client = _client()
        client.post("/ask", json={"question": "DROP TABLE traces", "connection_id": "conn_1"})
        body = client.get("/metrics").text
        self.assertIn('datahek_ask_results_total{outcome="query_denied"}', body)

    def test_metrics_not_self_counted(self):
        client = _client()
        client.get("/metrics")
        body = client.get("/metrics").text
        self.assertNotIn('endpoint="/metrics"', body)


if __name__ == "__main__":
    unittest.main()
