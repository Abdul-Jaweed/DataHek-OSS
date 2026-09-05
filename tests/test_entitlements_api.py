"""Entitlement enforcement — OSS limits checked before resource creation."""
import unittest

from fastapi.testclient import TestClient

from datahek.api.app import create_app
from datahek.defaults.container import build_app_container
from datahek.kernel.entitlements import EntitlementProvider


def _conn_payload(name: str):
    return {"name": name, "provider": "clickhouse", "host": "h", "port": 8123}


class TestConnectionLimit(unittest.TestCase):
    def test_sixth_connection_rejected(self):
        client = TestClient(create_app(build_app_container()))
        for i in range(1, 6):
            r = client.post("/connections", json=_conn_payload(f"ch{i}"))
            self.assertEqual(r.status_code, 201, r.text)
        r = client.post("/connections", json=_conn_payload("ch6"))
        self.assertEqual(r.status_code, 429, r.text)
        body = r.json()
        self.assertEqual(body["code"], "RATE_LIMITED")
        self.assertEqual(body["details"]["resource"], "connections")
        self.assertEqual(body["details"]["limit"], 5)
        self.assertEqual(body["details"]["current"], 5)

    def test_override_raises_limit(self):
        """Production/Enterprise replace the entitlement provider — no core changes."""
        container = build_app_container()
        container.override(EntitlementProvider, EntitlementProvider(
            {"connections": 8, "mcp.servers": 10, "prompt.templates": 25}))
        client = TestClient(create_app(container))
        for i in range(1, 8):
            r = client.post("/connections", json=_conn_payload(f"pg{i}"))
            self.assertEqual(r.status_code, 201, r.text)
        r = client.post("/connections", json=_conn_payload("pg8"))
        self.assertEqual(r.status_code, 201)
        r = client.post("/connections", json=_conn_payload("pg9"))
        self.assertEqual(r.status_code, 429)

    def test_health_shows_limits(self):
        client = TestClient(create_app(build_app_container()))
        body = client.get("/health").json()
        self.assertEqual(body["entitlements"]["connections"], 5)
        self.assertEqual(body["entitlements"]["mcp.servers"], 3)

    def test_limit_check_only_blocks_creation_not_ask(self):
        client = TestClient(create_app(build_app_container()))
        for i in range(1, 6):
            client.post("/connections", json=_conn_payload(f"ch{i}"))
        # asking on an existing connection still works (no creation involved)
        conn_id = client.get("/connections").json()[0]["id"]
        r = client.post("/ask", json={"question": "q", "connection_id": conn_id})
        # LLM not configured -> still reaches planning and fails typed, not with a limit error
        self.assertNotEqual(r.status_code, 429)


if __name__ == "__main__":
    unittest.main()