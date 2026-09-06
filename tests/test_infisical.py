"""InfisicalSecretsProvider + secret:// reference resolution."""
import asyncio
import unittest
from unittest import mock

import httpx

from datahek.contracts.connections import Connection
from datahek.contracts.models import ModelResponse
from datahek.contracts.providers import ConnectorCapabilities, DataProvider, ProviderKind
from datahek.contracts.secrets import SecretRef, SecretValue
from datahek.engine.executor import Engine, ProviderRegistry, _resolve_secrets
from datahek.engine.plan import LogicalPlan, ReadNode
from datahek.engine.schema import ColumnMeta, SchemaCatalog, SchemaService, TableMeta
from datahek.kernel.context import RequestContext


class _FakeSecrets:
    def __init__(self, value: str = "sup3r"):
        self.value = value
        self.refs: list[SecretRef] = []

    async def get_secret(self, ref: SecretRef) -> SecretValue:
        self.refs.append(ref)
        return SecretValue(value=self.value)

    async def store_secret(self, ref: SecretRef, value: SecretValue) -> None:
        raise NotImplementedError


class _RecordingProvider(DataProvider):
    provider_id = "fake"
    capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, dialect="fake", max_result_rows=10)

    def __init__(self):
        self.connected_with: Connection | None = None

    async def connect(self, connection):
        self.connected_with = connection
        return object()

    async def ping(self, client):
        return {"ok": True}

    async def compile_and_execute(self, client, plan, ctx):
        return {"columns": [], "rows": []}

    async def close(self, client):
        pass


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class TestInfisicalSecretsProvider(unittest.TestCase):
    def test_get_secret_uses_universal_auth(self):
        from datahek.defaults.infisical import InfisicalSecretsProvider

        provider = InfisicalSecretsProvider(host="https://infisical.test", client_id="cid",
                                            client_secret="csec", project_id="pid")
        with mock.patch.object(httpx.AsyncClient, "post", new=mock.AsyncMock()) as post, \
             mock.patch.object(httpx.AsyncClient, "get", new=mock.AsyncMock()) as get:
            post.return_value = _FakeResponse({"accessToken": "tok"})
            get.return_value = _FakeResponse({"secretValue": "sup3r"})
            val = asyncio.run(provider.get_secret(SecretRef(provider="infisical", name="pg_password")))

        self.assertEqual(val.value, "sup3r")
        login_url = post.call_args.args[0]
        self.assertEqual(login_url, "https://infisical.test/api/v1/auth/universal-auth/login")
        self.assertEqual(post.call_args.kwargs["json"], {"clientId": "cid", "clientSecret": "csec"})
        get_url = get.call_args.args[0]
        self.assertIn("/api/v3/secrets/raw/pg_password", get_url)
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(get.call_args.kwargs["params"], {"environment": "dev", "secretPath": "/"})

    def test_get_secret_derives_folder_from_ref_name(self):
        from datahek.defaults.infisical import InfisicalSecretsProvider

        provider = InfisicalSecretsProvider(host="https://infisical.test", client_id="cid",
                                            client_secret="csec")
        with mock.patch.object(httpx.AsyncClient, "post", new=mock.AsyncMock()) as post, \
             mock.patch.object(httpx.AsyncClient, "get", new=mock.AsyncMock()) as get:
            post.return_value = _FakeResponse({"accessToken": "tok"})
            get.return_value = _FakeResponse({"secretValue": "pw"})
            asyncio.run(provider.get_secret(SecretRef(provider="infisical", name="creds/pg_password")))

        get_url = get.call_args.args[0]
        self.assertIn("/api/v3/secrets/raw/pg_password", get_url)
        self.assertEqual(get.call_args.kwargs["params"]["secretPath"], "/creds")

    def test_store_secret_posts_secret_value(self):
        from datahek.defaults.infisical import InfisicalSecretsProvider

        provider = InfisicalSecretsProvider(host="https://infisical.test", client_id="cid",
                                            client_secret="csec")
        with mock.patch.object(httpx.AsyncClient, "post", new=mock.AsyncMock()) as post:
            post.return_value = _FakeResponse({"accessToken": "tok"})
            asyncio.run(provider.store_secret(SecretRef(provider="infisical", name="creds/pg_password"),
                                              SecretValue(value="sup3r")))

        store_calls = [c for c in post.call_args_list if "/api/v3/secrets/pg_password" in c.args[0]]
        self.assertEqual(len(store_calls), 1)
        self.assertEqual(store_calls[0].kwargs["json"],
                         {"secretValue": "sup3r", "environment": "dev", "secretPath": "/creds"})

    def test_token_cached_between_calls(self):
        from datahek.defaults.infisical import InfisicalSecretsProvider

        provider = InfisicalSecretsProvider(host="https://infisical.test", client_id="cid",
                                            client_secret="csec")
        with mock.patch.object(httpx.AsyncClient, "post", new=mock.AsyncMock()) as post, \
             mock.patch.object(httpx.AsyncClient, "get", new=mock.AsyncMock()) as get:
            post.return_value = _FakeResponse({"accessToken": "tok"})
            get.return_value = _FakeResponse({"secretValue": "a"})
            asyncio.run(provider.get_secret(SecretRef(provider="infisical", name="s1")))
            asyncio.run(provider.get_secret(SecretRef(provider="infisical", name="s2")))

        self.assertEqual(post.call_count, 1)


class TestResolveSecrets(unittest.TestCase):
    def test_executor_resolves_secret_refs(self):
        secrets = _FakeSecrets()
        conn = Connection(
            id="c1", name="pg", provider="postgres", org_id="o", project_id="p",
            host="localhost", database="postgres",
            settings={"username": "postgres", "password": "secret://infisical/creds/pg_password"},
        )
        resolved = asyncio.run(_resolve_secrets(conn, secrets))

        self.assertEqual(resolved.settings["password"], "sup3r")
        self.assertEqual(resolved.settings["username"], "postgres")
        self.assertEqual(secrets.refs, [SecretRef(provider="infisical", name="creds/pg_password")])

    def test_executor_resolve_noop_without_refs(self):
        secrets = _FakeSecrets()
        conn = Connection(id="c1", name="pg", provider="postgres", org_id="o", project_id="p",
                          settings={"username": "postgres", "password": "plain"})
        resolved = asyncio.run(_resolve_secrets(conn, secrets))

        self.assertIs(resolved, conn)
        self.assertEqual(secrets.refs, [])

    def test_execute_resolves_before_connect(self):
        provider = _RecordingProvider()
        registry = ProviderRegistry()
        registry.register(provider)
        engine = Engine(registry, secrets=_FakeSecrets())
        conn = Connection(
            id="c1", name="c", provider="fake", org_id="default", project_id="default",
            settings={"password": "secret://infisical/creds/pg_password"},
        )
        ctx = RequestContext(source="api")

        asyncio.run(engine.execute(ctx, LogicalPlan(nodes=[ReadNode(source="t", columns=["a"], limit=5)]), conn))

        self.assertIsNot(provider.connected_with, conn)
        self.assertEqual(provider.connected_with.settings["password"], "sup3r")


_PLAN = """{"nodes": [{"type": "ReadNode", "source": "traces", "columns": ["service"], "limit": 5}]}"""


class _PlannerModel:
    async def complete(self, request):
        return ModelResponse(content=_PLAN)

    async def stream(self, request):
        yield _PLAN


class _IntrospectRecordingProvider:
    provider_id = "fake"
    capabilities = ConnectorCapabilities(kind=ProviderKind.SQL, dialect="fake", max_result_rows=10)

    def __init__(self):
        self.introspected_with: Connection | None = None

    async def introspect(self, ctx, connection, source):
        self.introspected_with = connection
        return SchemaCatalog(source=source, tables=[
            TableMeta(name="traces", columns=[ColumnMeta(name="service", data_type="String")])])


class TestPlannerSecretResolution(unittest.TestCase):
    def test_plan_resolves_secret_settings_before_schema_discovery(self):
        from datahek.engine.planner import Planner

        secrets = _FakeSecrets(value="sup3r")
        provider = _IntrospectRecordingProvider()
        planner = Planner(model=_PlannerModel(), schema_service=SchemaService(), secrets=secrets)
        conn = Connection(
            id="c1", name="pg", provider="postgres", org_id="o", project_id="p",
            host="localhost", database="postgres",
            settings={"username": "postgres", "password": "secret://infisical/creds/pg_password"},
        )

        result = asyncio.run(planner.plan("top service?", RequestContext(source="api"), conn, provider))

        self.assertIsNotNone(result.plan)
        self.assertEqual(result.plan.nodes[0].source, "traces")
        self.assertIsNotNone(provider.introspected_with)
        self.assertEqual(provider.introspected_with.settings["password"], "sup3r")
        self.assertEqual(provider.introspected_with.settings["username"], "postgres")
        self.assertEqual(secrets.refs, [SecretRef(provider="infisical", name="creds/pg_password")])
        self.assertEqual(conn.settings["password"], "secret://infisical/creds/pg_password")

    def test_plan_without_secrets_introspects_raw_connection(self):
        from datahek.engine.planner import Planner

        provider = _IntrospectRecordingProvider()
        planner = Planner(model=_PlannerModel(), schema_service=SchemaService())
        conn = Connection(
            id="c1", name="pg", provider="postgres", org_id="o", project_id="p",
            settings={"password": "plain"},
        )

        asyncio.run(planner.plan("q", RequestContext(source="api"), conn, provider))

        self.assertIs(provider.introspected_with, conn)
        self.assertEqual(provider.introspected_with.settings["password"], "plain")