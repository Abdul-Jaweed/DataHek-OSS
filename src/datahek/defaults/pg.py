"""PgMetadata — shared PostgreSQL access for durable OSS stores (opt-in)."""
import psycopg
from datahek.kernel.config import Config, config_from_env


class MetadataConfig(Config):
    url: str = ""
    redis_url: str = ""


def metadata_config() -> MetadataConfig:
    return config_from_env(MetadataConfig, prefix="DATAHEK_METADATA_")


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS connections (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL,
  org_id TEXT NOT NULL, project_id TEXT NOT NULL,
  host TEXT, port INTEGER, database TEXT, settings_json TEXT NOT NULL,
  secret_ref_provider TEXT, secret_ref_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE connections ADD COLUMN IF NOT EXISTS secret_ref_provider TEXT;
ALTER TABLE connections ADD COLUMN IF NOT EXISTS secret_ref_name TEXT;
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, project_id TEXT NOT NULL,
  title TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS messages (
  id SERIAL PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, message_type TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS prompts (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, project_id TEXT NOT NULL,
  name TEXT NOT NULL, content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS evaluation_runs (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, project_id TEXT NOT NULL,
  run_json TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversations_org ON conversations(org_id);
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, project_id TEXT NOT NULL,
  resource_ref TEXT NOT NULL, requester TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending', decided_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS checkpoints (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, conversation_id TEXT,
  question TEXT NOT NULL, connection_id TEXT NOT NULL, plan_json TEXT NOT NULL,
  sql TEXT, row_count INTEGER, decision TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class PgMetadata:
    def __init__(self, url: str | None = None):
        cfg = metadata_config()
        self._url = url or cfg.url

    async def connect(self) -> psycopg.Connection:
        return psycopg.connect(self._url, connect_timeout=10, autocommit=True)

    async def init_schema(self) -> None:
        conn = await self.connect()
        try:
            conn.execute(_SCHEMA_SQL)
        finally:
            conn.close()

    async def close(self) -> None:
        pass  # per-call connections; nothing pooled
