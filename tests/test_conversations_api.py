"""Conversations API — creation, listing with cursor pagination, fetch by id."""
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from datahek.api.app import create_app
from datahek.defaults.container import build_app_container


class TestConversationsApi(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATAHEK_DB_PATH"] = os.path.join(self._tmp.name, "test.db")
        self.client = TestClient(create_app(build_app_container()))

    def tearDown(self):
        os.environ.pop("DATAHEK_DB_PATH", None)
        self._tmp.cleanup()

    def test_list_returns_created_conversations(self):
        conv_id = self.client.post("/conversations", json={"title": "list-probe"}).json()["id"]
        r = self.client.get("/conversations")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        ids = [item["id"] for item in body["items"]]
        self.assertIn(conv_id, ids)
        self.assertIsNone(body["next_cursor"])

    def test_list_pagination(self):
        for i in range(3):
            self.client.post("/conversations", json={"title": f"page-{i}"})
        first = self.client.get("/conversations", params={"limit": 2}).json()
        self.assertEqual(len(first["items"]), 2)
        self.assertIsNotNone(first["next_cursor"])
        second = self.client.get("/conversations",
                                 params={"limit": 2, "cursor": first["next_cursor"]}).json()
        self.assertEqual(len(second["items"]), 1)
        self.assertIsNone(second["next_cursor"])
        self.assertFalse(set(i["id"] for i in first["items"])
                         & set(i["id"] for i in second["items"]))

    def test_fetch_by_id(self):
        conv_id = self.client.post("/conversations", json={"title": "fetch-probe"}).json()["id"]
        r = self.client.get(f"/conversations/{conv_id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["id"], conv_id)


if __name__ == "__main__":
    unittest.main()
