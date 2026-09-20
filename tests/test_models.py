import os
import unittest
import uuid


class TestModelConfig(unittest.TestCase):
    def test_default_timeout_supports_slow_planning_calls(self):
        from datahek.defaults.models import ModelConfig

        self.assertGreaterEqual(ModelConfig().timeout_s, 120.0)

    def test_timeout_is_env_overridable(self):
        from datahek.kernel.config import config_from_env
        from datahek.defaults.models import ModelConfig

        os.environ["LLM_TIMEOUT_S"] = "45"
        try:
            self.assertEqual(config_from_env(ModelConfig, prefix="LLM_").timeout_s, 45.0)
        finally:
            os.environ.pop("LLM_TIMEOUT_S", None)


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
