"""Container wiring — env-driven persistent metadata (PostgreSQL + Redis) selection.

The container is built from ``os.environ``: with ``DATAHEK_METADATA_URL`` and
``DATAHEK_METADATA_REDIS_URL`` set, the durable PG/Redis stores are wired in;
without them the SQLite/in-memory defaults stay. Selection tests only assert
types — no live PG/Redis connection is required.
"""
import os
import unittest
from unittest.mock import patch

from datahek.contracts.connections import ConnectionManager
from datahek.contracts.evaluation import EvaluationStore
from datahek.contracts.misc import ConversationStore
from datahek.contracts.prompts import PromptStore
from datahek.defaults.connections import LocalConnectionManager
from datahek.defaults.connections_pg import PostgresConnectionManager
from datahek.defaults.container import build_app_container
from datahek.defaults.conversations import SqliteConversationStore
from datahek.defaults.conversations_pg import PostgresConversationStore
from datahek.defaults.evaluation import InMemoryEvaluationStore
from datahek.defaults.evaluation_pg import PostgresEvaluationStore
from datahek.defaults.pg import PgMetadata
from datahek.defaults.prompts import SqlitePromptStore
from datahek.defaults.prompts_pg import PostgresPromptStore
from datahek.defaults.redis_llm import RedisLlmSettingsStore

PG_URL = os.environ.get("DATAHEK_TEST_PG_URL") or "postgresql://datahek:datahek@127.0.0.1:55432/datahek"
REDIS_URL = os.environ.get("DATAHEK_TEST_REDIS_URL") or "redis://127.0.0.1:56379/0"

_ENV_KEYS = (
    "DATAHEK_METADATA_URL",
    "DATAHEK_METADATA_REDIS_URL",
    "DATAHEK_ENCRYPTION_KEY",
    "INFISICAL_HOST",
    "INFISICAL_CLIENT_ID",
    "INFISICAL_CLIENT_SECRET",
    "INFISICAL_PROJECT_ID",
)


class TestContainerMetadataSelection(unittest.TestCase):
    def test_pg_and_redis_stores_wired_when_urls_set(self):
        with patch.dict(os.environ, {
            "DATAHEK_METADATA_URL": PG_URL,
            "DATAHEK_METADATA_REDIS_URL": REDIS_URL,
        }, clear=False):
            c = build_app_container()
        self.assertIsInstance(c.resolve(ConnectionManager), PostgresConnectionManager)
        self.assertIsInstance(c.resolve(ConversationStore), PostgresConversationStore)
        self.assertIsInstance(c.resolve(PromptStore), PostgresPromptStore)
        self.assertIsInstance(c.resolve(EvaluationStore), PostgresEvaluationStore)
        self.assertTrue(c.has(PgMetadata))
        self.assertTrue(c.has(RedisLlmSettingsStore))
        self.assertIsInstance(c.resolve(RedisLlmSettingsStore), RedisLlmSettingsStore)

    def test_sqlite_and_in_memory_defaults_when_urls_unset(self):
        with patch.dict(os.environ):
            for key in _ENV_KEYS:
                os.environ.pop(key, None)
            c = build_app_container()
        self.assertIsInstance(c.resolve(ConnectionManager), LocalConnectionManager)
        self.assertIsInstance(c.resolve(ConversationStore), SqliteConversationStore)
        self.assertIsInstance(c.resolve(PromptStore), SqlitePromptStore)
        self.assertIsInstance(c.resolve(EvaluationStore), InMemoryEvaluationStore)
        self.assertFalse(c.has(PgMetadata))
        self.assertFalse(c.has(RedisLlmSettingsStore))

    def test_encryption_key_forwarded_to_pg_connection_manager(self):
        with patch.dict(os.environ, {
            "DATAHEK_METADATA_URL": PG_URL,
            "DATAHEK_ENCRYPTION_KEY": "test-encryption-key",
        }, clear=False):
            c = build_app_container()
        mgr = c.resolve(ConnectionManager)
        self.assertIsInstance(mgr, PostgresConnectionManager)
        self.assertIsNotNone(mgr._fernet)


if __name__ == "__main__":
    unittest.main()
