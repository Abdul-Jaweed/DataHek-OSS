"""CLI surface — one-shot ask, connections, interactive loop."""
import asyncio
import io
import unittest
from contextlib import redirect_stdout

from datahek.cli import ask_one, find_connection_by_name, main
from datahek.contracts.connections import Connection, ConnectionManager
from datahek.contracts.models import ModelResponse
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
from datahek.defaults.container import build_app_container
from datahek.engine.executor import ProviderRegistry
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext


class _FakeModel:
    async def complete(self, request):
        return ModelResponse(content=PLAN if "PLAN" in globals() else "{}")
    async def stream(self, request):
        yield "ok"


PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}"""


class _FakeProvider:
    provider_id = "clickhouse"
    capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)
    async def connect(self, connection): return object()
    async def introspect(self, ctx, connection, source):
        return SchemaCatalog(source=source, tables=[
            TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")])])
    async def compile_and_execute(self, client, plan, ctx):
        return {"columns": [{"name": "service", "type": "String"}], "rows": [("payment-api",)]}
    async def close(self, client): pass


def _container():
    from datahek.contracts.models import ModelProvider
    from datahek.contracts.reasoner import Reasoner
    from datahek.engine.reasoner import ModelReasoner

    class ReasonerModel:
        async def complete(self, request):
            return ModelResponse(content="The top service is payment-api.")
        async def stream(self, request):
            yield "ok"

    c = build_app_container()
    c.override(ModelProvider, _FakeModel())
    c.override(Reasoner, ModelReasoner(ReasonerModel()))
    registry = ProviderRegistry()
    registry.register(_FakeProvider())
    c.override(ProviderRegistry, registry)
    return c


class TestFindConnection(unittest.TestCase):
    async def _setup(self):
        c = _container()
        conn_mgr = c.resolve(ConnectionManager)
        ctx = RequestContext(source="cli")
        await conn_mgr.add(ctx, Connection(id="conn_1", name="ch1", provider="clickhouse",
                                           org_id="default", project_id="default"))
        return conn_mgr, ctx

    def test_find_by_name(self):
        conn_mgr, ctx = asyncio.run(self._setup())
        conn = asyncio.run(find_connection_by_name(conn_mgr, ctx, "ch1"))
        self.assertEqual(conn.id, "conn_1")

    def test_find_by_id(self):
        conn_mgr, ctx = asyncio.run(self._setup())
        conn = asyncio.run(find_connection_by_name(conn_mgr, ctx, "conn_1"))
        self.assertEqual(conn.name, "ch1")

    def test_missing_raises(self):
        from datahek.kernel.errors import DatahekError

        conn_mgr, ctx = asyncio.run(self._setup())
        with self.assertRaises(DatahekError):
            asyncio.run(find_connection_by_name(conn_mgr, ctx, "nope"))


class TestAskOne(unittest.TestCase):
    def test_ask_returns_answer(self):
        c = _container()
        conn_mgr = c.resolve(ConnectionManager)
        asyncio.run(conn_mgr.add(RequestContext(source="cli"), Connection(
            id="conn_1", name="ch1", provider="clickhouse", org_id="default", project_id="default")))
        answer = asyncio.run(ask_one(c, "which service?", "ch1"))
        self.assertEqual(answer["answer"], "The top service is payment-api.")
        self.assertEqual(answer["rows"], [{"service": "payment-api"}])

    def test_ask_prints_answer(self):
        c = _container()
        conn_mgr = c.resolve(ConnectionManager)
        asyncio.run(conn_mgr.add(RequestContext(source="cli"), Connection(
            id="conn_1", name="ch1", provider="clickhouse", org_id="default", project_id="default")))
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(ask_one(c, "which service?", "ch1"))
        self.assertIn("payment-api", buf.getvalue())


class TestMain(unittest.TestCase):
    def test_connections_empty(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["connections"])
        self.assertIn("No connections", buf.getvalue())

    def test_unknown_command(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["frobnicate"])
        self.assertIn("Usage", buf.getvalue())

    def test_ask_unknown_connection(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["ask", "question", "--connection", "nope"])
        self.assertIn("not found", buf.getvalue())


if __name__ == "__main__":
    unittest.main()