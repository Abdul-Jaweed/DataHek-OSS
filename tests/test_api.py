"""API surface — health, connections, ask (question → plan → execute)."""
import asyncio
import unittest

from fastapi.testclient import TestClient

from datahek.api.app import create_app
from datahek.contracts.connections import Connection
from datahek.contracts.models import ModelProvider
from datahek.contracts.models import ModelResponse
from datahek.contracts.providers import ConnectorCapabilities, ProviderKind, ReadOnlyLevel
from datahek.engine.executor import ProviderRegistry
from datahek.engine.schema import ColumnMeta, SchemaCatalog, TableMeta
from datahek.kernel.context import RequestContext


class _FakeModel:
    def __init__(self, response: str):
        self._response = response

    async def complete(self, request):
        return ModelResponse(content=self._response)

    async def stream(self, request):
        yield self._response


class _FakeProvider:
    provider_id = "clickhouse"
    capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, dialect="clickhouse",
                                         read_only=ReadOnlyLevel.STRUCTURAL, max_result_rows=1000)

    async def connect(self, connection: Connection):
        return object()

    async def ping(self, client):
        return {"ok": True}

    async def introspect(self, ctx: RequestContext, connection: Connection, source: str) -> SchemaCatalog:
        return SchemaCatalog(
            source=source,
            tables=[TableMeta(name="traces", columns=[
                ColumnMeta(name="service", data_type="String"),
                ColumnMeta(name="status", data_type="String"),
            ], row_count=12)],
        )

    async def compile_and_execute(self, client, plan, ctx):
        return {"columns": [{"name": "service", "type": "String"}, {"name": "n", "type": "UInt64"}],
                "rows": [("payment-api", 7), ("auth-service", 3)]}

    async def close(self, client):
        pass


def _app_with(model_response: str):
    from datahek.defaults.container import build_app_container

    container = build_app_container()
    container.override(ModelProvider,
                       _FakeModel(model_response))
    registry = ProviderRegistry()
    registry.register(_FakeProvider())
    container.override(ProviderRegistry, registry)
    return create_app(container)


class TestHealth(unittest.TestCase):
    def test_health(self):
        client = TestClient(_app_with("{}"))
        r = client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["version"], "0.2.0")
        self.assertFalse(body["capabilities"]["sso"])
        self.assertIn("entitlements", body)


class TestConnections(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_app_with("{}"))

    def test_create_and_list(self):
        r = self.client.post("/connections", json={
            "name": "ch1", "provider": "clickhouse",
            "host": "localhost", "port": 8123, "database": "default",
            "settings": {"username": "default"},
        })
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual(body["provider"], "clickhouse")
        self.assertIn("id", body)

        r = self.client.get("/connections")
        self.assertEqual(r.status_code, 200)
        names = [c["name"] for c in r.json()]
        self.assertIn("ch1", names)

    def test_duplicate_name_rejected(self):
        payload = {"name": "dup", "provider": "clickhouse", "host": "h", "port": 8123}
        self.client.post("/connections", json=payload)
        r = self.client.post("/connections", json=payload)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["code"], "CONNECTION_EXISTS")

    def test_unsupported_provider(self):
        r = self.client.post("/connections", json={"name": "x", "provider": "mongo", "host": "h"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "UNSUPPORTED_PROVIDER")

    def test_invalid_body(self):
        r = self.client.post("/connections", json={})
        self.assertEqual(r.status_code, 422)


class TestAsk(unittest.TestCase):
    PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"],
        "filter": "status = 'error'", "group_by": ["service"],
        "aggregates": [{"function": "count", "column": "*", "alias": "n"}],
        "order_by": ["n DESC"], "limit": 10}]}"""

    def setUp(self):
        self.client = TestClient(_app_with(self.PLAN))
        r = self.client.post("/connections", json={
            "name": "ch1", "provider": "clickhouse",
            "host": "localhost", "port": 8123, "database": "default",
            "settings": {"username": "default"},
        })
        self.conn_id = r.json()["id"]

    def test_ask_returns_result(self):
        r = self.client.post("/ask", json={"question": "errors by service", "connection_id": self.conn_id})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIsNone(body["clarification"])
        self.assertIn("row_count", body)
        self.assertIn("columns", body)
        self.assertTrue(body["plan_sources"])

    def test_ask_unknown_connection(self):
        r = self.client.post("/ask", json={"question": "q", "connection_id": "nope"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["code"], "CONNECTION_NOT_FOUND")

    def test_ask_without_connections(self):
        client = TestClient(_app_with(self.PLAN))
        r = client.post("/ask", json={"question": "q", "connection_id": "nope"})
        self.assertEqual(r.status_code, 404)

    def test_error_contract_shape(self):
        r = self.client.post("/ask", json={"question": "q", "connection_id": "nope"})
        body = r.json()
        self.assertEqual(set(body.keys()), {"code", "message", "details"})

    def test_ask_requires_question(self):
        r = self.client.post("/ask", json={"connection_id": self.conn_id})
        self.assertEqual(r.status_code, 422)


class TestClarification(unittest.TestCase):
    def test_clarification_returned(self):
        client = TestClient(_app_with('{"nodes": [], "clarification": "Which table?"}'))
        r = client.post("/connections", json={
            "name": "c", "provider": "clickhouse", "host": "h", "port": 8123,
        })
        conn_id = r.json()["id"]
        r = client.post("/ask", json={"question": "q", "connection_id": conn_id})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["clarification"], "Which table?")
        self.assertIsNone(body["rows"])


class TestErrorHygiene(unittest.TestCase):
    def test_schema_failure_is_typed_502(self):
        from datahek.api.app import create_app
        from datahek.defaults.container import build_app_container
        from datahek.contracts.models import ModelResponse
        from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
        from datahek.engine.executor import ProviderRegistry

        container = build_app_container()

        class FakeModel:
            async def complete(self, request):
                return ModelResponse(content="{}")
            async def stream(self, request):
                yield "{}"

        class BrokenSchemaProvider:
            provider_id = "clickhouse"
            capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)
            async def connect(self, connection): return object()
            async def introspect(self, ctx, connection, source):
                raise RuntimeError("driver internal /tmp secret")
            async def compile_and_execute(self, client, plan, ctx):
                return {"columns": [], "rows": []}
            async def close(self, client): pass

        container.override(ModelProvider, FakeModel())
        registry = ProviderRegistry()
        registry.register(BrokenSchemaProvider())
        container.override(ProviderRegistry, registry)
        client = TestClient(create_app(container))
        r = client.post("/connections", json={"name": "ch", "provider": "clickhouse", "host": "h"})
        conn_id = r.json()["id"]
        r = client.post("/ask", json={"question": "q", "connection_id": conn_id})
        self.assertEqual(r.status_code, 502, r.text)
        self.assertEqual(r.json()["code"], "CONNECTION_FAILED")
        self.assertNotIn("secret", r.text)

    def test_unexpected_exception_is_sanitized_500(self):
        from datahek.api.app import create_app
        from datahek.defaults.container import build_app_container
        from datahek.contracts.models import ModelResponse
        from datahek.contracts.providers import ConnectorCapabilities, ProviderKind
        from datahek.engine.executor import ProviderRegistry

        container = build_app_container()

        class FakeModel:
            async def complete(self, request):
                return ModelResponse(content="{}")
            async def stream(self, request):
                yield "{}"

        class ExplodingProvider:
            provider_id = "clickhouse"
            capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, max_result_rows=1000)
            async def connect(self, connection): return object()
            async def introspect(self, ctx, connection, source):
                raise ValueError("boom secret internal detail")
            async def compile_and_execute(self, client, plan, ctx):
                return {"columns": [], "rows": []}
            async def close(self, client): pass

        container.override(ModelProvider, FakeModel())
        registry = ProviderRegistry()
        registry.register(ExplodingProvider())
        container.override(ProviderRegistry, registry)

        class _Unwrapped:
            """Force the schema path to raise outside the typed wrapper by
            hitting an endpoint that calls get_catalog directly."""

        # The /ask path wraps schema errors; simulate an unhandled error via a
        # direct call to an endpoint that is guaranteed to raise elsewhere.
        app = create_app(container)
        client = TestClient(app, raise_server_exceptions=False)
        # Register a route that raises for the sanitizer test.
        @app.get("/boom")
        async def boom():
            raise RuntimeError("hidden internal detail")

        r = client.get("/boom")
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.json()["code"], "INTERNAL")
        self.assertNotIn("hidden internal detail", r.text)


if __name__ == "__main__":
    unittest.main()

class TestConnectionEndpoints(unittest.TestCase):
    def _client(self, registry):
        from datahek.api.app import create_app
        from datahek.defaults.container import build_app_container
        from datahek.engine.executor import ProviderRegistry
        from fastapi.testclient import TestClient
        c = build_app_container()
        c.override(ProviderRegistry, registry)
        return TestClient(create_app(container=c))

    def test_test_endpoint_ok(self):
        from datahek.engine.executor import ProviderRegistry
        from datahek.connectors.sqlite import SQLiteProvider
        registry = ProviderRegistry()
        registry.register(SQLiteProvider())
        client = self._client(registry)
        r = client.post("/connections/test", json={
            "name": "probe", "provider": "sqlite", "host": ":memory:",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"], body)
        self.assertIn("latency_ms", body)

    def test_test_endpoint_reports_failure(self):
        import asyncio
        from datahek.engine.executor import ProviderRegistry
        from datahek.contracts.providers import ConnectorCapabilities, ProviderKind

        class BoomProvider:
            provider_id = "boom"
            capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, dialect="boom")

            async def connect(self, connection):
                raise RuntimeError("boom")

        registry = ProviderRegistry()
        registry.register(BoomProvider())
        client = self._client(registry)
        r = client.post("/connections/test", json={
            "name": "probe", "provider": "boom", "host": "x",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertIn("boom", body["error"])

    def test_delete_connection(self):
        from datahek.engine.executor import ProviderRegistry
        from datahek.connectors.sqlite import SQLiteProvider
        registry = ProviderRegistry()
        registry.register(SQLiteProvider())
        client = self._client(registry)
        created = client.post("/connections", json={
            "name": "tmp1", "provider": "sqlite", "host": ":memory:",
        })
        self.assertEqual(created.status_code, 201)
        cid = created.json()["id"]
        r = client.delete(f"/connections/{cid}")
        self.assertEqual(r.status_code, 204)
        remaining = client.get("/connections").json()
        self.assertNotIn(cid, [c["id"] for c in remaining])

    def test_delete_missing_connection_404(self):
        from datahek.engine.executor import ProviderRegistry
        from datahek.connectors.sqlite import SQLiteProvider
        registry = ProviderRegistry()
        registry.register(SQLiteProvider())
        client = self._client(registry)
        r = client.delete("/connections/nope")
        self.assertEqual(r.status_code, 404)


class TestAuthLogin(unittest.TestCase):
    def setUp(self):
        from datahek.api.app import create_app
        from datahek.defaults.container import build_app_container
        from fastapi.testclient import TestClient
        self.client = TestClient(create_app(container=build_app_container()))

    def test_login_default_credentials(self):
        r = self.client.post("/auth/login", json={"username": "datahek", "password": "datahek"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["user"], "datahek")
        self.assertEqual(body["token"], "datahek")
        self.assertIn("analyst", body["roles"])

    def test_login_wrong_password(self):
        r = self.client.post("/auth/login", json={"username": "datahek", "password": "wrong"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["code"], "UNAUTHORIZED")

    def test_health_reports_auth_mode(self):
        r = self.client.get("/health")
        self.assertIn("auth_mode", r.json())


class TestLlmSettings(unittest.TestCase):
    def setUp(self):
        from datahek.api.app import create_app
        from datahek.defaults.container import build_app_container
        from fastapi.testclient import TestClient
        self.client = TestClient(create_app(container=build_app_container()))

    def test_get_llm_settings(self):
        r = self.client.get("/settings/llm")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("base_url", body)
        self.assertIn("model", body)
        self.assertIn("api_key_set", body)

    def test_configure_llm_settings(self):
        r = self.client.post("/settings/llm", json={"model": "test-model-42"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["model"], "test-model-42")
        again = self.client.get("/settings/llm").json()
        self.assertEqual(again["model"], "test-model-42")


class TestConnectionUpdate(unittest.TestCase):
    def setUp(self):
        from datahek.api.app import create_app
        from datahek.defaults.container import build_app_container
        from fastapi.testclient import TestClient
        self.client = TestClient(create_app(container=build_app_container()))

    def _create(self, name="editme", **extra):
        payload = {"name": name, "provider": "sqlite", "host": ":memory:", **extra}
        r = self.client.post("/connections", json=payload)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def test_update_fields(self):
        cid = self._create()
        r = self.client.put(f"/connections/{cid}", json={
            "name": "renamed", "provider": "sqlite", "host": "/tmp/x.db", "database": "d1"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["name"], "renamed")
        self.assertEqual(body["host"], "/tmp/x.db")

    def test_update_requires_known_provider(self):
        cid = self._create()
        r = self.client.put(f"/connections/{cid}", json={"name": "x", "provider": "mongo"})
        self.assertEqual(r.status_code, 400)

    def test_update_missing_connection_404(self):
        r = self.client.put("/connections/nope", json={"name": "x", "provider": "sqlite"})
        self.assertEqual(r.status_code, 404)

    def test_update_duplicate_name_409(self):
        self._create(name="first")
        cid2 = self._create(name="second")
        r = self.client.put(f"/connections/{cid2}", json={"name": "first", "provider": "sqlite"})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["code"], "CONNECTION_EXISTS")


class TestRequestContextIdentity(unittest.TestCase):
    def test_identity_organization_propagates(self):
        from datahek.api.app import _request_context
        from datahek.contracts.auth import AuthenticatedIdentity
        from datahek.kernel.context import RequestContext

        class _EnterpriseIdentity(AuthenticatedIdentity):
            organization_id: str = "acme"

        class _Req:
            approval_id = None
            question = "q"
            user_id = "anon"

        ctx = _request_context(_Req(), _EnterpriseIdentity(
            user_id="alice", authenticated=True, roles=frozenset({"admin"}),
            permissions=frozenset({"connection:query"})))
        self.assertIsInstance(ctx, RequestContext)
        self.assertEqual(ctx.organization_id, "acme")
        self.assertEqual(ctx.user_id, "alice")
        self.assertTrue(ctx.authenticated)

    def test_plain_identity_defaults_org(self):
        from datahek.api.app import _request_context
        from datahek.contracts.auth import AuthenticatedIdentity

        class _Req:
            approval_id = None
            question = "q"
            user_id = "anon"

        ctx = _request_context(_Req(), AuthenticatedIdentity(user_id="bob", authenticated=True))
        self.assertEqual(ctx.organization_id, "default")

    def test_unauthenticated_uses_request_user(self):
        from datahek.api.app import _request_context
        from datahek.contracts.auth import AuthenticatedIdentity

        class _Req:
            approval_id = None
            question = "q"
            user_id = "carol"

        ctx = _request_context(_Req(), AuthenticatedIdentity(user_id="bob", authenticated=False))
        self.assertEqual(ctx.user_id, "carol")
        self.assertFalse(ctx.authenticated)
