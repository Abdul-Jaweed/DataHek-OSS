"""Checkpoints — save, inspect, and deterministically replay stored plans."""
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
        return {"columns": [{"name": "service", "type": "String"}], "rows": [("payment-api",), ("auth-service",)]}

    async def close(self, client):
        pass


def _client(db_path):
    import os
    os.environ["DATAHEK_DB_PATH"] = db_path
    try:
        c = build_app_container()
        c.override(ModelProvider, _FakeModel())
        registry = ProviderRegistry()
        registry.register(_FakeProvider())
        c.override(ProviderRegistry, registry)
        c.override(ConnectionManager, LocalConnectionManager([
            Connection(id="conn_1", name="ch1", provider="clickhouse", org_id="default", project_id="default")]))
        return TestClient(create_app(c))
    finally:
        os.environ.pop("DATAHEK_DB_PATH", None)


class TestCheckpointStore(unittest.TestCase):
    def test_roundtrip(self):
        import asyncio
        import tempfile
        from datahek.defaults.checkpoints import SqliteCheckpointStore
        from datahek.kernel.context import RequestContext

        with tempfile.TemporaryDirectory() as d:
            store = SqliteCheckpointStore(f"{d}/cp.db")
            ctx = RequestContext(source="api")
            cid = asyncio.run(store.save(ctx, {
                "question": "q", "connection_id": "c1", "plan": {"nodes": []},
                "sql": "SELECT 1", "row_count": 1, "decision": "ALLOW"}))
            item = asyncio.run(store.get(ctx, cid))
            self.assertEqual(item["question"], "q")
            self.assertEqual(item["sql"], "SELECT 1")
            self.assertEqual(len(asyncio.run(store.list(ctx))), 1)


class TestCheckpointApi(unittest.TestCase):
    def test_ask_saves_checkpoint_and_replay_executes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            client = _client(f"{d}/db.sqlite")
            r = client.post("/ask", json={"question": "show traces", "connection_id": "conn_1"})
            self.assertEqual(r.status_code, 200, r.text)

            listed = client.get("/checkpoints").json()
            self.assertEqual(len(listed), 1)
            cp_id = listed[0]["id"]
            self.assertEqual(listed[0]["question"], "show traces")
            self.assertIn("SELECT service FROM traces", listed[0]["sql"])

            replay = client.post(f"/checkpoints/{cp_id}/replay")
            self.assertEqual(replay.status_code, 200, replay.text)
            body = replay.json()
            self.assertTrue(body["replayed"])
            self.assertEqual(body["rows"], [{"service": "payment-api"}, {"service": "auth-service"}])

    def test_unknown_checkpoint_404(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            client = _client(f"{d}/db.sqlite")
            self.assertEqual(client.get("/checkpoints/nope").status_code, 404)
            self.assertEqual(client.post("/checkpoints/nope/replay").status_code, 404)


if __name__ == "__main__":
    unittest.main()


class TestForkAndDiff(unittest.TestCase):
    def test_fork_reruns_and_links_lineage(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            client = _client(f"{d}/db.sqlite")
            client.post("/ask", json={"question": "show traces", "connection_id": "conn_1"})
            original = client.get("/checkpoints").json()[0]["id"]

            fork = client.post(f"/checkpoints/{original}/fork")
            self.assertEqual(fork.status_code, 200, fork.text)
            body = fork.json()
            self.assertEqual(body.get("forked_from"), original)
            self.assertTrue(body.get("new_checkpoint_id"))

            newest = client.get("/checkpoints").json()[0]
            self.assertEqual(newest["forked_from"], original)

    def test_diff_reports_changes(self):
        import asyncio
        import tempfile
        from datahek.defaults.checkpoints import SqliteCheckpointStore
        from datahek.kernel.context import RequestContext

        with tempfile.TemporaryDirectory() as d:
            path = f"{d}/cp.db"
            store = SqliteCheckpointStore(path)
            ctx = RequestContext(source="api")

            async def seed():
                await store.save(ctx, {"id": "cp_a", "question": "q1", "connection_id": "c1",
                                       "plan": {}, "sql": "SELECT 1", "row_count": 1})
                await store.save(ctx, {"id": "cp_b", "question": "q1", "connection_id": "c1",
                                       "plan": {}, "sql": "SELECT 2", "row_count": 2})

            asyncio.run(seed())

            from fastapi.testclient import TestClient
            from datahek.api.app import create_app
            from datahek.defaults.container import build_app_container
            import os

            os.environ["DATAHEK_DB_PATH"] = path
            try:
                client = TestClient(create_app(container=build_app_container()))
                r = client.get("/checkpoints/cp_a/diff/cp_b")
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertFalse(body["identical"])
                self.assertEqual(body["changes"]["sql"], {"left": "SELECT 1", "right": "SELECT 2"})
                self.assertEqual(body["changes"]["row_count"], {"left": 1, "right": 2})

                same = client.get("/checkpoints/cp_a/diff/cp_a")
                self.assertTrue(same.json()["identical"])
            finally:
                os.environ.pop("DATAHEK_DB_PATH", None)
