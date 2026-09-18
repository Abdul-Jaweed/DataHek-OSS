"""MCP tools — the full catalog through the in-process FastMCP client."""
import asyncio
import json
import os
import tempfile
import unittest

from fastmcp import Client

from datahek.contracts.connections import Connection
from datahek.contracts.connections import Connection, ConnectionManager
from datahek.contracts.models import ModelProvider, ModelResponse
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
from datahek.contracts.saved import SavedQuery
from datahek.engine.executor import ProviderRegistry
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.defaults.connections import LocalConnectionManager
from datahek.defaults.container import build_app_container
from datahek.kernel.context import RequestContext

PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}"""


class _Model:
    async def complete(self, request):
        system = request["messages"][0]["content"]
        if "explain" in system.lower():
            return ModelResponse(content="8 traces total.")
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
        return {"columns": [{"name": "service", "type": "String"}], "rows": [("auth",), ("order",)]}

    async def close(self, client):
        pass


def _server(db_path):
    os.environ["DATAHEK_DB_PATH"] = db_path
    try:
        c = build_app_container()
        c.override(ModelProvider, _Model())
        registry = ProviderRegistry()
        registry.register(_Provider())
        c.override(ProviderRegistry, registry)
        c.override(ConnectionManager, LocalConnectionManager([
            Connection(id="conn_1", name="ch1", provider="clickhouse",
                       org_id="default", project_id="default", database="default")]))
        from datahek.mcp_server import build_mcp_server

        return build_mcp_server(c), c
    finally:
        os.environ.pop("DATAHEK_DB_PATH", None)


def _text(result):
    try:
        return result.content[0].text
    except Exception:
        return str(getattr(result, "data", result))


class TestMcpToolCatalog(unittest.TestCase):
    def test_tool_names_registered(self):
        with tempfile.TemporaryDirectory() as d:
            server, _ = _server(f"{d}/db.sqlite")

            async def run():
                async with Client(server) as client:
                    tools = await client.list_tools()
                    return sorted(t.name for t in tools)

            names = asyncio.run(run())
            self.assertEqual(names, [
                "data.ask", "data.list_connections", "data.list_metrics",
                "data.list_tables", "data.replay_checkpoint",
                "data.run_saved_query", "data.table_schema",
            ])

    def test_list_connections(self):
        with tempfile.TemporaryDirectory() as d:
            server, _ = _server(f"{d}/db.sqlite")

            async def run():
                async with Client(server) as client:
                    return _text(await client.call_tool("data.list_connections", {}))

            out = asyncio.run(run())
            self.assertIn("ch1", out)
            self.assertIn("clickhouse", out)
            self.assertNotIn("password", out.lower())

    def test_list_metrics(self):
        with tempfile.TemporaryDirectory() as d:
            server, container = _server(f"{d}/db.sqlite")
            from datahek.contracts.semantics import Metric, SemanticStore

            ctx = RequestContext(source="mcp")
            asyncio.run(container.resolve(SemanticStore).create(
                ctx, Metric(id="m1", name="error_count", table="traces",
                            aggregate="count", column="*", filter="status = 'error'")))

            async def run():
                async with Client(server) as client:
                    return _text(await client.call_tool("data.list_metrics", {}))

            out = asyncio.run(run())
            self.assertIn("error_count", out)
            self.assertIn("status = 'error'", out)

    def test_run_saved_query_full_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            server, container = _server(f"{d}/db.sqlite")
            from datahek.contracts.saved import SavedQueryStore

            ctx = RequestContext(source="mcp")
            asyncio.run(container.resolve(SavedQueryStore).create(
                ctx, SavedQuery(id="sq1", name="auth traces", question="list services",
                                connection_id="conn_1")))

            async def run():
                async with Client(server) as client:
                    return _text(await client.call_tool("data.run_saved_query", {"name_or_id": "auth traces"}))

            out = asyncio.run(run())
            self.assertIn("auth", out)  # rows flowed through plan → execute → explain

    def test_replay_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            server, container = _server(f"{d}/db.sqlite")
            from datahek.contracts.misc import CheckpointStore

            ctx = RequestContext(source="mcp")
            cid = asyncio.run(container.resolve(CheckpointStore).save(ctx, {
                "question": "list services", "connection_id": "conn_1",
                "plan": json.loads(PLAN), "sql": "SELECT service FROM traces LIMIT 5",
                "row_count": 2, "decision": "ALLOW"}))

            async def run():
                async with Client(server) as client:
                    return _text(await client.call_tool("data.replay_checkpoint", {"checkpoint_id": cid}))

            out = asyncio.run(run())
            self.assertIn("[replay", out)
            self.assertIn("service=auth", out)

    def test_replay_unknown_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            server, _ = _server(f"{d}/db.sqlite")

            async def run():
                async with Client(server) as client:
                    return _text(await client.call_tool("data.replay_checkpoint", {"checkpoint_id": "nope"}))

            self.assertIn("not found", asyncio.run(run()))


if __name__ == "__main__":
    unittest.main()
