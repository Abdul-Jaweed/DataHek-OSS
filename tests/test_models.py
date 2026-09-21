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


class TestTransientRetry(unittest.TestCase):
    def test_complete_retries_once_on_timeout(self):
        import asyncio
        from unittest import mock

        import httpx

        from datahek.defaults.models import OpenAICompatibleModelProvider

        provider = OpenAICompatibleModelProvider()
        calls = {"n": 0}

        async def fake_post(self, payload):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ReadTimeout("upstream slow")
            return {"choices": [{"message": {"content": "ok"}}]}

        with mock.patch.object(OpenAICompatibleModelProvider, "_post", fake_post):
            response = asyncio.run(
                provider.complete({"messages": [{"role": "user", "content": "hi"}]}))
        self.assertEqual(response.content, "ok")
        self.assertEqual(calls["n"], 2)

    def test_complete_does_not_retry_client_errors(self):
        import asyncio
        from unittest import mock

        import httpx

        from datahek.contracts.models import ModelProviderError
        from datahek.defaults.models import OpenAICompatibleModelProvider

        provider = OpenAICompatibleModelProvider()
        calls = {"n": 0}

        async def fake_post(self, payload):
            calls["n"] += 1
            request = httpx.Request("POST", "https://example.test/chat/completions")
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

        with mock.patch.object(OpenAICompatibleModelProvider, "_post", fake_post):
            with self.assertRaises(ModelProviderError) as caught:
                asyncio.run(
                    provider.complete({"messages": [{"role": "user", "content": "hi"}]}))
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(calls["n"], 1)
