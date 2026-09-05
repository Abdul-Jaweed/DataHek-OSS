"""Basic web UI — served at /, consumes /ask/stream via SSE."""
import unittest

from fastapi.testclient import TestClient

from datahek.api.app import create_app
from datahek.defaults.container import build_app_container


class TestWebUI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(build_app_container()))

    def test_index_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertIn("DataHek", r.text)

    def test_page_has_chat_widgets(self):
        r = self.client.get("/")
        self.assertIn("chat-input", r.text)
        self.assertIn("/ask/stream", r.text)
        self.assertIn("/connections", r.text)

    def test_ui_path_alias(self):
        r = self.client.get("/ui")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()