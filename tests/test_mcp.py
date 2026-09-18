"""MCP server — the same guarded pipeline exposed over FastMCP."""
import asyncio
import unittest

from datahek.contracts.connections import Connection, ConnectionManager
from datahek.contracts.models import ModelResponse
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
from datahek.defaults.container import build_app_container
from datahek.engine.executor import ProviderRegistry
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext


PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}"""


class _FakeModel:
    async def complete(self, request):
        return ModelResponse(content=PLAN)
    async def stream(self, request):
        yield PLAN


class _FakeProvider:
    provider_id = "clickhouse"
    capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)
    async def connect(self, connection): return object()
    async def introspect(self, ctx, connection, source):
        return SchemaCatalog(source=source, tables=[
            TableMeta(name="traces", columns=[
                ColumnMeta(name="service", data_type="String"),
                ColumnMeta(name="status", data_type="String"),
            ], row_count=12),
        ])
    async def compile_and_execute(self, client, plan, ctx):
        return {"columns": [{"name": "service", "type": "String"}], "rows": [("payment-api",)]}
    async def close(self, client): pass


def _container_with_conn():
    from datahek.contracts.models import ModelProvider
    from datahek.contracts.reasoner import Reasoner
    from datahek.defaults.connections import LocalConnectionManager
    from datahek.engine.reasoner import ModelReasoner

    class ReasonerModel:
        async def complete(self, request):
            return ModelResponse(content="payment-api leads the list.")
        async def stream(self, request):
            yield "ok"

    c = build_app_container()
    c.override(ModelProvider, _FakeModel())
    c.override(Reasoner, ModelReasoner(ReasonerModel()))
    registry = ProviderRegistry()
    registry.register(_FakeProvider())
    c.override(ProviderRegistry, registry)
    c.override(ConnectionManager, LocalConnectionManager([
        Connection(id="conn_1", name="ch1", provider="clickhouse", org_id="default", project_id="default"),
    ]))
    return c


def _server():
    from datahek.mcp_server import build_mcp_server
    return build_mcp_server(_container_with_conn())


async def _call(name, args):
    server = _server()
    result = await server.call_tool(name, args)
    return result.content[0].text


class TestMCPRegistration(unittest.TestCase):
    def test_registers_tool_catalog(self):
        server = _server()
        tools = asyncio.run(server.list_tools())
        names = {t.name for t in tools}
        self.assertEqual(names, {
            "data.list_tables", "data.table_schema", "data.ask",
            "data.list_connections", "data.list_metrics",
            "data.run_saved_query", "data.replay_checkpoint",
        })


class TestMCPTools(unittest.TestCase):
    def test_list_tables(self):
        text = asyncio.run(_call("data.list_tables", {"connection": "ch1"}))
        self.assertIn("traces", text)
        self.assertIn("12", text)

    def test_table_schema(self):
        text = asyncio.run(_call("data.table_schema", {"connection": "ch1", "table": "traces"}))
        self.assertIn("service", text)
        self.assertIn("status", text)

    def test_table_schema_unknown_table(self):
        text = asyncio.run(_call("data.table_schema", {"connection": "ch1", "table": "ghost"}))
        self.assertIn("not found", text)

    def test_ask_returns_explanation_and_rows(self):
        text = asyncio.run(_call("data.ask", {"question": "top service?", "connection": "ch1"}))
        self.assertIn("payment-api leads the list.", text)
        self.assertIn("payment-api", text)

    def test_ask_unknown_connection_errors(self):
        text = asyncio.run(_call("data.ask", {"question": "q", "connection": "nope"}))
        self.assertIn("not found", text)

    def test_unknown_tool_not_registered(self):
        server = _server()
        tools = asyncio.run(server.list_tools())
        self.assertNotIn("data.drop_table", {t.name for t in tools})


if __name__ == "__main__":
    unittest.main()