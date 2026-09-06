"""RedisLlmSettingsStore — persistent runtime LLM settings (opt-in)."""
import asyncio
import os
import unittest

REDIS_URL = os.environ.get("DATAHEK_TEST_REDIS_URL") or "redis://127.0.0.1:56379/0"


@unittest.skipUnless(os.environ.get("DATAHEK_TEST_REDIS_URL"), "redis test instance not running")
class TestRedisLlmSettingsStore(unittest.TestCase):
    def test_save_then_load_roundtrip(self):
        from datahek.defaults.redis_llm import RedisLlmSettingsStore

        async def run():
            store = RedisLlmSettingsStore(url=REDIS_URL)
            await store.save({"base_url": "https://x/v1", "api_key": "k", "model": "m"})
            loaded = await store.load()
            self.assertEqual(loaded["model"], "m")
            self.assertEqual(loaded["base_url"], "https://x/v1")
            await store.clear()
            self.assertIsNone(await store.load())
            await store.close()

        asyncio.run(run())

    def test_save_partial_leaves_other_fields(self):
        from datahek.defaults.redis_llm import RedisLlmSettingsStore

        async def run():
            store = RedisLlmSettingsStore(url=REDIS_URL)
            await store.save({"base_url": "https://a/v1", "model": "m1"})
            await store.save({"model": "m2"})
            loaded = await store.load()
            self.assertEqual(loaded["base_url"], "https://a/v1")
            self.assertEqual(loaded["model"], "m2")
            await store.clear()
            await store.close()

        asyncio.run(run())

    def test_provider_loads_redis_override(self):
        from datahek.defaults.models import OpenAICompatibleModelProvider
        from datahek.defaults.redis_llm import RedisLlmSettingsStore

        async def run():
            store = RedisLlmSettingsStore(url=REDIS_URL)
            await store.save({"model": "redis-model"})
            provider = OpenAICompatibleModelProvider(settings_store=store)
            await provider.reload_from_store()
            self.assertEqual(provider.model_id(), "redis-model")
            await store.clear()
            await store.close()

        asyncio.run(run())