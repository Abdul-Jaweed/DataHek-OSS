"""Audit coverage — auth failures and administrative CRUD actions."""
import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from datahek.api.app import create_app
from datahek.contracts.auth import AuthProvider
from datahek.defaults.auth import AuthConfig, LocalAuthProvider
from datahek.defaults.container import build_app_container


def _events(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


class TestAuditEvents(unittest.TestCase):
    def _client(self, tmp: str, local_auth: bool = False):
        os.environ["DATAHEK_AUDIT_PATH"] = os.path.join(tmp, "audit.jsonl")
        c = build_app_container()
        if local_auth:
            c.override(AuthConfig, AuthConfig(mode="local", local_users="{}"))
            c.override(AuthProvider, LocalAuthProvider(users={"alice": "s3cret"}))
        return TestClient(create_app(c))

    def tearDown(self):
        os.environ.pop("DATAHEK_AUDIT_PATH", None)

    def test_auth_failure_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp, local_auth=True)
            r = client.get("/connections")
            self.assertEqual(r.status_code, 401)
            failures = [e for e in _events(os.path.join(tmp, "audit.jsonl"))
                        if e["event_type"] == "auth.failure"]
            self.assertEqual(len(failures), 1, failures)
            self.assertEqual(failures[0]["decision"], "DENY")
            self.assertEqual(failures[0]["payload"]["reason"], "missing_api_key")

    def test_connection_crud_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp)
            created = client.post("/connections",
                                  json={"name": "audit-crud", "provider": "clickhouse", "host": "h"})
            self.assertEqual(created.status_code, 201, created.text)
            conn_id = created.json()["id"]
            self.assertEqual(client.delete(f"/connections/{conn_id}").status_code, 204)
            events = _events(os.path.join(tmp, "audit.jsonl"))
            kinds = [e["event_type"] for e in events]
            self.assertIn("connection.create", kinds)
            self.assertIn("connection.delete", kinds)
            create = next(e for e in events if e["event_type"] == "connection.create")
            self.assertEqual(create["actor"], "anonymous")
            self.assertEqual(create["resource_ref"], conn_id)


if __name__ == "__main__":
    unittest.main()
