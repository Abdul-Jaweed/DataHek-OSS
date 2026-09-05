"""Optional authentication — DATAHEK_AUTH_MODE=local enforces API keys."""
import unittest

from fastapi.testclient import TestClient

from datahek.contracts.auth import AuthProvider
from datahek.api.app import create_app
from datahek.defaults.container import build_app_container
from datahek.defaults.auth import AuthConfig, LocalAuthProvider
from datahek.kernel.di import Container


def _local_app(users: dict | None = None):
    c: Container = build_app_container()
    c.override(AuthConfig, AuthConfig(mode="local", local_users="{}"))
    c.override(AuthProvider,
               LocalAuthProvider(users=users or {"alice": "s3cret"}))
    return TestClient(create_app(c))


class TestAuthDisabled(unittest.TestCase):
    def test_open_by_default(self):
        client = TestClient(create_app(build_app_container()))
        r = client.post("/connections", json={"name": "c", "provider": "clickhouse", "host": "h"})
        self.assertEqual(r.status_code, 201, r.text)

    def test_health_open_in_local_mode(self):
        client = _local_app()
        r = client.get("/health")
        self.assertEqual(r.status_code, 200)


class TestAuthLocal(unittest.TestCase):
    def setUp(self):
        self.client = _local_app()

    def test_create_without_key_rejected(self):
        r = self.client.post("/connections", json={"name": "c", "provider": "clickhouse", "host": "h"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["code"], "UNAUTHORIZED")

    def test_create_with_key(self):
        r = self.client.post("/connections", json={"name": "c", "provider": "clickhouse", "host": "h"},
                             headers={"X-API-Key": "s3cret"})
        self.assertEqual(r.status_code, 201, r.text)

    def test_bearer_token_accepted(self):
        r = self.client.post("/connections", json={"name": "c", "provider": "clickhouse", "host": "h"},
                             headers={"Authorization": "Bearer s3cret"})
        self.assertEqual(r.status_code, 201)

    def test_invalid_key_rejected(self):
        r = self.client.post("/connections", json={"name": "c", "provider": "clickhouse", "host": "h"},
                             headers={"X-API-Key": "wrong"})
        self.assertEqual(r.status_code, 401)

    def test_ask_requires_key(self):
        r = self.client.post("/ask", json={"question": "q", "connection_id": "x"})
        self.assertEqual(r.status_code, 401)

    def test_list_connections_requires_key(self):
        r = self.client.get("/connections")
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/connections", headers={"X-API-Key": "s3cret"})
        self.assertEqual(r.status_code, 200)


class TestLocalAuthProviderApiKey(unittest.TestCase):
    def test_api_key_matches_user_password(self):
        import asyncio

        p = LocalAuthProvider(users={"alice": "s3cret", "bob": "other"})
        ident = asyncio.run(p.authenticate_api_key("s3cret"))
        self.assertTrue(ident.authenticated)
        self.assertEqual(ident.user_id, "alice")

    def test_unknown_token(self):
        import asyncio

        p = LocalAuthProvider(users={"alice": "s3cret"})
        ident = asyncio.run(p.authenticate_api_key("nope"))
        self.assertFalse(ident.authenticated)


class TestEnvDrivenAuth(unittest.TestCase):
    def test_env_mode_local_enforced(self):
        import os

        from datahek.api.app import create_app

        os.environ["DATAHEK_AUTH_MODE"] = "local"
        os.environ["DATAHEK_AUTH_LOCAL_USERS"] = '{"alice": "s3cret"}'
        try:
            client = TestClient(create_app(build_app_container()))
            r = client.post("/connections", json={"name": "c", "provider": "clickhouse", "host": "h"})
            self.assertEqual(r.status_code, 401)
            r = client.post("/connections", json={"name": "c", "provider": "clickhouse", "host": "h"},
                            headers={"X-API-Key": "s3cret"})
            self.assertEqual(r.status_code, 201, r.text)
        finally:
            os.environ.pop("DATAHEK_AUTH_MODE", None)
            os.environ.pop("DATAHEK_AUTH_LOCAL_USERS", None)

    def test_env_mode_none_open(self):
        import os

        from datahek.api.app import create_app

        os.environ["DATAHEK_AUTH_MODE"] = "none"
        try:
            client = TestClient(create_app(build_app_container()))
            r = client.post("/connections", json={"name": "c", "provider": "clickhouse", "host": "h"})
            self.assertEqual(r.status_code, 201)
        finally:
            os.environ.pop("DATAHEK_AUTH_MODE", None)


if __name__ == "__main__":
    unittest.main()