"""Audit search — filtered reads over the JSONL trail."""
import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient


def _write(path, events):
    with open(path, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


EVENTS = [
    {"event_type": "guardrail.decision", "actor": "datahek", "decision": "ALLOW", "payload": {"x": 1}},
    {"event_type": "query.execution", "actor": "datahek", "decision": "ALLOW", "payload": {"rows": 8}},
    {"event_type": "guardrail.decision", "actor": "alice", "decision": "DENY", "payload": {"reason": "injection"}},
]


class TestAuditSearch(unittest.TestCase):
    def test_filters(self):
        from datahek.defaults.audit_search import search_audit

        with tempfile.TemporaryDirectory() as d:
            path = f"{d}/audit.jsonl"
            _write(path, EVENTS)

            all_events = search_audit(path=path, limit=10)
            self.assertEqual(len(all_events), 3)
            self.assertEqual(all_events[0]["actor"], "alice")  # newest first

            denied = search_audit(path=path, decision="DENY")
            self.assertEqual(len(denied), 1)

            by_type = search_audit(path=path, event_type="query.execution")
            self.assertEqual(len(by_type), 1)
            self.assertEqual(by_type[0]["payload"]["rows"], 8)

            contained = search_audit(path=path, contains="injection")
            self.assertEqual(len(contained), 1)
            self.assertEqual(contained[0]["decision"], "DENY")

            limited = search_audit(path=path, limit=2)
            self.assertEqual(len(limited), 2)

    def test_missing_file_is_empty(self):
        from datahek.defaults.audit_search import search_audit

        self.assertEqual(search_audit(path="/nonexistent/audit.jsonl"), [])


class TestAuditApi(unittest.TestCase):
    def test_endpoint_serves_filtered_events(self):
        with tempfile.TemporaryDirectory() as d:
            path = f"{d}/audit.jsonl"
            _write(path, EVENTS)
            os.environ["DATAHEK_AUDIT_PATH"] = path
            try:
                from datahek.api.app import create_app
                from datahek.defaults.container import build_app_container

                client = TestClient(create_app(container=build_app_container()))
                r = client.get("/audit?decision=DENY")
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(len(r.json()), 1)
                self.assertEqual(r.json()[0]["actor"], "alice")
            finally:
                os.environ.pop("DATAHEK_AUDIT_PATH", None)


if __name__ == "__main__":
    unittest.main()
