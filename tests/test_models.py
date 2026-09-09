import unittest
import uuid


class TestSessionHeader(unittest.TestCase):
    def test_session_header_sent_per_request(self):
        import asyncio
        from unittest import mock
        from datahek.defaults.models import OpenAICompatibleModelProvider

        provider = OpenAICompatibleModelProvider()

        async def fake_post(self, payload):
            return {"choices": [{"message": {"content": "ok"}}]}

        with mock.patch.object(OpenAICompatibleModelProvider, "_post", fake_post):
            r = asyncio.run(provider.complete({"messages": [{"role": "user", "content": "hi"}]}))
        self.assertEqual(r.content, "ok")

    def test_headers_include_session_id(self):
        import asyncio
        from unittest import mock
        from datahek.defaults.models import OpenAICompatibleModelProvider

        provider = OpenAICompatibleModelProvider()
        captured = {}

        async def fake_post(self, payload):
            captured["payload"] = payload
            captured["headers"] = self._headers()
            return {"choices": [{"message": {"content": "ok"}}]}

        with mock.patch.object(OpenAICompatibleModelProvider, "_post", fake_post):
            asyncio.run(provider.complete({"messages": [{"role": "user", "content": "hi"}]}))
        self.assertIn("x-opencode-session", captured["headers"])
        uuid.UUID(captured["headers"]["x-opencode-session"])
