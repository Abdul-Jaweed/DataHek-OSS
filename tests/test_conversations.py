"""SQLite conversation store — tenant-scoped, persistent (OSS default)."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from datahek.defaults.conversations import SqliteConversationStore
from datahek.kernel.context import RequestContext


def _run(coro):
    return asyncio.run(coro)


def _store(tmp: str):
    return SqliteConversationStore(Path(tmp) / "conv.db")


class TestConversationStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = _store(self._tmp.name)
        self.ctx = RequestContext(source="api", user_id="alice")

    def tearDown(self):
        self._tmp.cleanup()

    def test_create_and_get(self):
        _run(self.store.create(self.ctx, "conv_1", title="first"))
        conv = _run(self.store.get(self.ctx, "conv_1"))
        self.assertEqual(conv["id"], "conv_1")
        self.assertEqual(conv["title"], "first")
        self.assertEqual(conv["messages"], [])

    def test_append_and_get_messages(self):
        _run(self.store.create(self.ctx, "conv_1"))
        _run(self.store.append_message(self.ctx, "conv_1", {"role": "user", "content": "hello"}))
        _run(self.store.append_message(self.ctx, "conv_1", {"role": "assistant", "content": "hi", "message_type": "answer"}))
        conv = _run(self.store.get(self.ctx, "conv_1"))
        self.assertEqual(len(conv["messages"]), 2)
        self.assertEqual(conv["messages"][0]["role"], "user")
        self.assertEqual(conv["messages"][1]["message_type"], "answer")

    def test_unknown_conversation_returns_none(self):
        self.assertIsNone(_run(self.store.get(self.ctx, "conv_nope")))

    def test_append_to_unknown_raises(self):
        with self.assertRaises(KeyError):
            _run(self.store.append_message(self.ctx, "conv_nope", {"role": "user", "content": "x"}))

    def test_tenant_scoping(self):
        _run(self.store.create(self.ctx, "conv_1"))
        other = RequestContext(source="api", organization_id="other-org", project_id="other")
        self.assertIsNone(_run(self.store.get(other, "conv_1")))
        with self.assertRaises(PermissionError):
            _run(self.store.append_message(other, "conv_1", {"role": "user", "content": "x"}))

    def test_list_by_project(self):
        _run(self.store.create(self.ctx, "conv_1", title="a"))
        _run(self.store.create(self.ctx, "conv_2", title="b"))
        page = _run(self.store.list_by_project(self.ctx, self.ctx.project_id))
        ids = [c["id"] for c in page["items"]]
        self.assertEqual(set(ids), {"conv_1", "conv_2"})
        self.assertIsNone(page["next_cursor"])

    def test_list_by_project_scoped(self):
        _run(self.store.create(self.ctx, "conv_1"))
        other = RequestContext(source="api", organization_id="o2", project_id="p2")
        _run(self.store.create(other, "conv_2"))
        page = _run(self.store.list_by_project(self.ctx, self.ctx.project_id))
        self.assertEqual([c["id"] for c in page["items"]], ["conv_1"])

    def test_persistence_across_instances(self):
        _run(self.store.create(self.ctx, "conv_1"))
        _run(self.store.append_message(self.ctx, "conv_1", {"role": "user", "content": "persisted"}))
        store2 = _store(self._tmp.name)
        conv = _run(store2.get(self.ctx, "conv_1"))
        self.assertEqual(conv["messages"][0]["content"], "persisted")

    def test_env_path_override(self):
        import os

        target = str(Path(self._tmp.name) / "env.db")
        os.environ["DATAHEK_DB_PATH"] = target
        try:
            store = SqliteConversationStore()
            _run(store.create(self.ctx, "conv_1"))
        finally:
            os.environ.pop("DATAHEK_DB_PATH", None)
        self.assertTrue(Path(target).exists())


class TestAskRecordsConversation(unittest.TestCase):
    def test_ask_with_conversation_records_turns(self):
        from fastapi.testclient import TestClient

        from datahek.api.app import create_app
        from datahek.defaults.container import build_app_container
        from datahek.contracts.models import ModelResponse
        from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
        from datahek.engine.executor import ProviderRegistry
        from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta

        PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}"""

        class FakeModel:
            async def complete(self, request):
                return ModelResponse(content=PLAN)
            async def stream(self, request):
                yield PLAN

        class FakeProvider:
            provider_id = "clickhouse"
            capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)
            async def connect(self, connection): return object()
            async def introspect(self, ctx, connection, source):
                return SchemaCatalog(source=source, tables=[
                    TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")])])
            async def compile_and_execute(self, client, plan, ctx):
                return {"columns": [{"name": "service", "type": "String"}], "rows": [("api",)]}
            async def close(self, client): pass

        container = build_app_container()
        container.override(__import__("datahek.contracts.models", fromlist=["ModelProvider"]).ModelProvider, FakeModel())
        registry = ProviderRegistry()
        registry.register(FakeProvider())
        container.override(ProviderRegistry, registry)
        client = TestClient(create_app(container))

        r = client.post("/conversations", json={"title": "t1"})
        self.assertEqual(r.status_code, 201, r.text)
        conv_id = r.json()["id"]

        r = client.post("/connections", json={"name": "ch", "provider": "clickhouse", "host": "h"})
        conn_id = r.json()["id"]

        r = client.post("/ask", json={"question": "services?", "connection_id": conn_id, "conversation_id": conv_id})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["conversation_id"], conv_id)

        r = client.get(f"/conversations/{conv_id}")
        self.assertEqual(r.status_code, 200)
        messages = r.json()["messages"]
        roles = [m["role"] for m in messages]
        self.assertEqual(roles, ["user", "assistant"])
        self.assertEqual(messages[0]["content"], "services?")

    def test_ask_without_conversation_no_record(self):
        from fastapi.testclient import TestClient

        from datahek.api.app import create_app
        from datahek.defaults.container import build_app_container
        from datahek.contracts.models import ModelResponse
        from datahek.engine.executor import ProviderRegistry
        from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
        from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta

        container = build_app_container()

        class FakeModel:
            async def complete(self, request):
                return ModelResponse(content="{}")
            async def stream(self, request):
                yield "{}"

        class FakeProvider:
            provider_id = "clickhouse"
            capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)
            async def connect(self, connection): return object()
            async def introspect(self, ctx, connection, source):
                return SchemaCatalog(source=source, tables=[
                    TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")])])
            async def compile_and_execute(self, client, plan, ctx):
                return {"columns": [], "rows": []}
            async def close(self, client): pass

        container.override(__import__("datahek.contracts.models", fromlist=["ModelProvider"]).ModelProvider, FakeModel())
        registry = ProviderRegistry()
        registry.register(FakeProvider())
        container.override(ProviderRegistry, registry)
        client = TestClient(create_app(container))
        r = client.post("/connections", json={"name": "ch", "provider": "clickhouse", "host": "h"})
        conn_id = r.json()["id"]
        r = client.post("/ask", json={"question": "q", "connection_id": conn_id})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json().get("conversation_id"))


if __name__ == "__main__":
    unittest.main()