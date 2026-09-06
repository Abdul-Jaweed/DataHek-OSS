# Persistent Metadata (PostgreSQL + Redis) & Infisical Secrets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace in-memory state (connections, evaluation runs, LLM runtime settings) with PostgreSQL + Redis, and move credentials (DB passwords, login users, LLM keys) into Infisical — while keeping the current SQLite/in-memory behavior as the zero-config default.

**Architecture:** A single env flag (`DATAHEK_METADATA_URL`) switches the durable stores (connections, conversations, prompts, evaluations) from the current defaults to PostgreSQL implementations behind the *existing* contracts (`ConnectionManager`, `ConversationStore`, `PromptStore`, `EvaluationStore`). A new `RedisLlmSettingsStore` persists runtime LLM overrides so they survive API restarts. A new `InfisicalSecretsProvider` implements the *existing* `SecretsProvider` contract; connection settings may reference secrets via a `secret://` prefix, resolved at connect time. When Infisical env vars are absent, the current env/local behavior is unchanged.

**Tech Stack:** psycopg (already a dependency), `redis` (new optional dep `datahek-core[redis]`), httpx (already a dependency — Infisical API client needs no new SDK), `cryptography` (optional, Fernet encryption at rest).

## Global Constraints

- All existing 257 tests must stay green **unchanged**; new functionality is opt-in via env vars.
- Never store plaintext credentials in logs, responses, or API payloads; `/connections` list responses must NOT include `settings`.
- Contracts (`datahek/contracts/*.py`) may only be extended, never edited for OSS defaults' sake.
- New optional dependencies go under a new `[redis]` extra in `pyproject.toml`; `cryptography` is optional (extra `[crypto]`).
- Integration tests requiring real PostgreSQL/Redis must **skip** when the test services are unavailable (`DATAHEK_TEST_PG_URL`, `DATAHEK_TEST_REDIS_URL` env-gated).
- Infisical self-hosted is NOT bundled into the OSS docker-compose (it requires its own stack) — documented as external, optional.

---

### Task 1: PgMetadata helper + schema DDL

**Files:**
- Create: `src/datahek/defaults/pg.py`
- Test: `tests/test_pg_metadata.py`

**Interfaces:**
- Produces: `class PgMetadata` with:
  - `__init__(self, url: str | None = None)` — url from `DATAHEK_METADATA_URL` env fallback
  - `async def connect(self) -> psycopg.Connection` — new autocommit connection per call, `connect_timeout=10`
  - `async def init_schema(self) -> None` — idempotent `CREATE TABLE IF NOT EXISTS` for: `connections`, `conversations`, `messages`, `prompts`, `evaluation_runs`
  - `async def close(self) -> None`

**DDL (exact, used in `init_schema`):**
```sql
CREATE TABLE IF NOT EXISTS connections (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL,
  org_id TEXT NOT NULL, project_id TEXT NOT NULL,
  host TEXT, port INTEGER, database TEXT, settings_json TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
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
```

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pg_metadata.py
import os
import unittest

PG_URL = os.environ.get("DATAHEK_TEST_PG_URL")
if not PG_URL:
    PG_URL = "postgresql://datahek:datahek@localhost:55432/datahek"  # docker test container


@unittest.skipUnless(os.environ.get("DATAHEK_TEST_PG_URL") or _port_open(), "postgres test container not running")
class TestPgMetadata(unittest.TestCase):
    def test_init_schema_and_roundtrip(self):
        import asyncio
        from datahek.defaults.pg import PgMetadata

        async def run():
            pg = PgMetadata(url=PG_URL)
            await pg.init_schema()
            conn = await pg.connect()
            cur = conn.execute("SELECT to_regclass('public.connections')")
            self.assertIsNotNone(cur.fetchone()[0])
            await pg.close()

        asyncio.run(run())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_pg_metadata -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'datahek.defaults.pg'`

- [ ] **Step 3: Write minimal implementation** — `src/datahek/defaults/pg.py`:

```python
"""PgMetadata — shared PostgreSQL access for durable OSS stores (opt-in)."""
import psycopg
from datahek.kernel.config import Config, config_from_env


class MetadataConfig(Config):
    url: str = ""
    redis_url: str = ""


def metadata_config() -> MetadataConfig:
    return config_from_env(MetadataConfig, prefix="DATAHEK_METADATA_")


_SCHEMA_SQL = """... (DDL above, verbatim) ..."""


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
```

- [ ] **Step 4: Run test to verify it passes** (with the docker test PG running)
- [ ] **Step 5: Commit** `feat: add PgMetadata helper + schema DDL`

---

### Task 2: PostgresConnectionManager (persistent + encrypted at rest)

**Files:**
- Create: `src/datahek/defaults/connections_pg.py`
- Modify: `tests/test_connections_pg.py` (new file)
- Modify: `pyproject.toml` — add `crypto = ["cryptography>=42"]` extra

**Interfaces:**
- Consumes: `PgMetadata` (Task 1), `Connection` (existing dataclass: `id, name, provider, org_id, project_id, host, port, database, settings`)
- Produces: `class PostgresConnectionManager` implementing `ConnectionManager` (same methods as `LocalConnectionManager`: `get_connection`, `list_connections`, `add`, `remove`), constructor `(pg: PgMetadata, encryption_key: str | None = None)`.

**Behavior:**
- `settings` stored as JSON; when `encryption_key` is set, the JSON is Fernet-encrypted before insert and decrypted on read (`cryptography`).
- `add` raises `DatahekError(ErrorCode.CONNECTION_EXISTS)` on duplicate name (org-scoped).
- `get_connection` raises `CONNECTION_NOT_FOUND` when missing; `FORBIDDEN` on org mismatch.
- Secret values in settings may be `secret://infisical/<path>/<key>` — stored as-is (never resolved at rest).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_connections_pg.py
class TestPostgresConnectionManager(unittest.TestCase):
    def test_add_get_list_remove(self):
        import asyncio
        from datahek.defaults.pg import PgMetadata
        from datahek.defaults.connections_pg import PostgresConnectionManager
        from datahek.contracts.connections import Connection
        from datahek.kernel.context import RequestContext

        async def run():
            pg = PgMetadata(url=PG_URL)
            await pg.init_schema()
            mgr = PostgresConnectionManager(pg, encryption_key="test-key-32-bytes-long!!")
            ctx = RequestContext(source="api")
            conn = Connection(id="c1", name="ch1", provider="clickhouse",
                              org_id="default", project_id="default",
                              settings={"password": "s3cret"})
            await mgr.add(ctx, conn)
            got = await mgr.get_connection(ctx, "c1")
            self.assertEqual(got.settings["password"], "s3cret")
            self.assertEqual(len(await mgr.list_connections(ctx)), 1)
            await mgr.remove(ctx, "c1")
            self.assertEqual(len(await mgr.list_connections(ctx)), 0)
            await pg.close()

        asyncio.run(run())

    def test_duplicate_name_rejected(self):  # same pattern, expect CONNECTION_EXISTS
        ...

    def test_settings_encrypted_at_rest(self):
        # after add, read the raw row via SQL and assert "s3cret" not in settings_json
        ...
```

- [ ] **Step 2: Run test to verify it fails** — `ModuleNotFoundError: datahek.defaults.connections_pg`
- [ ] **Step 3: Write minimal implementation** (`connections_pg.py`) — use `json.dumps(settings)`, Fernet with `encryption_key` (if provided, derive via `base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())`), psycopg parameterized SQL, `WHERE org_id = %s` scoping on every query.
- [ ] **Step 4: Run tests → PASS** (`python -m unittest tests.test_connections_pg`)
- [ ] **Step 5: Commit** `feat: PostgresConnectionManager with encrypted-at-rest settings`

---

### Task 3: PostgresConversationStore + PostgresPromptStore

**Files:**
- Create: `src/datahek/defaults/conversations_pg.py`, `src/datahek/defaults/prompts_pg.py`
- Test: `tests/test_conversations_pg.py`, `tests/test_prompts_pg.py`

**Interfaces:**
- Consumes: `PgMetadata` (Task 1)
- Produces:
  - `class PostgresConversationStore` implementing `ConversationStore` (methods per `datahek/contracts/misc.py`: `create`, `get`, `append_message`, `list`, `delete`)
  - `class PostgresPromptStore` implementing `PromptStore` (methods per `datahek/contracts/prompts.py`: `create`, `get`, `update`, `delete`, `list`)

**Behavior:** messages stored in `messages` table joined to `conversations`; `get` returns `{"id", "title", "messages": [...]}` shaped exactly like the existing `SqliteConversationStore.get` (copy its return shape from `src/datahek/defaults/conversations.py`). `append_message` inserts a `messages` row with `message_type`. Prompt `list` returns `[{id, name, content}]`; count limit (3) stays enforced by entitlements (unchanged, API layer).

- [ ] **Step 1: Write the failing tests** — mirror the existing `tests/test_conversations.py` and `tests/test_prompts.py` cases but constructed with `PostgresConversationStore(PgMetadata(url=PG_URL))` and a fresh `init_schema()` per test class.
- [ ] **Step 2: Run → FAIL** (modules missing)
- [ ] **Step 3: Implement both stores** — parameterized SQL; `append_message` uses `INSERT ... RETURNING id`; conversations `delete` cascades messages (DDL already has `ON DELETE CASCADE`).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: PostgresConversationStore + PostgresPromptStore`

---

### Task 4: PostgresEvaluationStore

**Files:**
- Create: `src/datahek/defaults/evaluation_pg.py`
- Test: `tests/test_evaluation_pg.py`

**Interfaces:**
- Consumes: `PgMetadata` (Task 1)
- Produces: `class PostgresEvaluationStore` implementing `EvaluationStore` (`record`, `list`, `aggregate` from `datahek/contracts/evaluation.py`).

**Behavior:** `record(ctx, run: dict)` inserts `json.dumps(run)` into `evaluation_runs` with a generated id (`entity_id("eval")`); `list` returns parsed dicts newest-first; `aggregate` returns the same shape as `InMemoryEvaluationStore.aggregate` (copy from `src/datahek/defaults/evaluation.py` — `{"total", "passed", "pass_rate", "runs"}`).

- [ ] **Steps 1–2: Failing tests** (mirror `tests/test_evaluation.py` cases against PG store)
- [ ] **Step 3: Implement**
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** `feat: PostgresEvaluationStore`

---

### Task 5: RedisLlmSettingsStore — persistent runtime LLM config

**Files:**
- Create: `src/datahek/defaults/redis_llm.py`
- Modify: `src/datahek/defaults/models.py` (load Redis override at startup when configured)
- Modify: `src/datahek/api/app.py` (POST `/settings/llm` also writes Redis; GET reads Redis-first)
- Modify: `pyproject.toml` — add `redis = ["redis>=5.0"]` extra
- Test: `tests/test_redis_llm.py`

**Interfaces:**
- Consumes: `MetadataConfig.redis_url` (`DATAHEK_METADATA_REDIS_URL`) from Task 1
- Produces:
  - `class RedisLlmSettingsStore` — `async def load(self) -> dict | None` (reads hash `datahek:llm:settings` → `{base_url, api_key, model}`), `async def save(self, settings: dict) -> None`, `async def clear(self) -> None`
  - Uses `redis.asyncio.from_url(redis_url, decode_responses=True)`, one client per store, `close()` on shutdown.

**Behavior:** `OpenAICompatibleModelProvider.__init__` gains `settings_store: RedisLlmSettingsStore | None = None`; when set and `load()` returns values, they override the env config via `self._config = replace(self._config, ...)`. `POST /settings/llm` calls `store.save({...exclude_none})` after `model_provider.configure(...)`; `GET /settings/llm` returns provider state (already includes Redis-loaded values).

- [ ] **Step 1: Write the failing test** (redis test instance via `DATAHEK_TEST_REDIS_URL`, skip-if-unavailable):

```python
# tests/test_redis_llm.py
class TestRedisLlmSettingsStore(unittest.TestCase):
    def test_save_then_load_roundtrip(self):
        import asyncio
        from datahek.defaults.redis_llm import RedisLlmSettingsStore

        async def run():
            store = RedisLlmSettingsStore(url=REDIS_URL)
            await store.save({"base_url": "https://x/v1", "api_key": "k", "model": "m"})
            loaded = await store.load()
            self.assertEqual(loaded["model"], "m")
            await store.clear()
            self.assertIsNone(await store.load())
            await store.close()

        asyncio.run(run())

    def test_provider_loads_redis_override(self):
        # save {"model": "redis-model"}; construct OpenAICompatibleModelProvider(settings_store=store);
        # assert provider.model_id() == "redis-model"; clear
        ...
```

- [ ] **Step 2: Run → FAIL** (`ModuleNotFoundError`)
- [ ] **Step 3: Implement** `redis_llm.py` + provider hook + API writes (keep API behavior identical when no Redis configured — `c.has(RedisLlmSettingsStore)` guard)
- [ ] **Step 4: Run → PASS** (both tests + existing `tests/test_api.py::TestLlmSettings` still green)
- [ ] **Step 5: Commit** `feat: Redis-backed runtime LLM settings`

---

### Task 6: InfisicalSecretsProvider + secret references in connections

**Files:**
- Create: `src/datahek/defaults/infisical.py`
- Modify: `src/datahek/engine/executor.py` — resolve `secret://` settings before `provider.connect`
- Modify: `src/datahek/defaults/container.py` — register `InfisicalSecretsProvider` when `INFISICAL_*` envs present, else keep `EnvSecretsProvider`
- Test: `tests/test_infisical.py`

**Interfaces:**
- Consumes: existing `SecretsProvider` contract (`get_secret(SecretRef)`, `store_secret(SecretRef, SecretValue)`)
- Produces:
  - `class InfisicalConfig(Config)`: `host: str = ""`, `client_id: str = ""`, `client_secret: str = ""`, `project_id: str = ""`, prefix `INFISICAL_`
  - `class InfisicalSecretsProvider` implementing `SecretsProvider`:
    - `_token()` — POST `{host}/api/v1/auth/universal-auth/login` `{clientId, clientSecret}` → `accessToken` (httpx, cached 55 min)
    - `get_secret(ref)` — GET `{host}/api/v3/secrets/raw/{ref.name}?environment=dev&secretPath=/{ref.provider==infisical path part}` with Bearer token; returns `SecretValue(secret_value)`
    - `store_secret(ref, value)` — POST `{host}/api/v3/secrets/{ref.name}` with `{secretValue, environment, secretPath}`; idempotent upsert
    - `is_configured() -> bool`

**Secret reference syntax (no contract change):** a `Connection.settings` value of the form `secret://infisical/<path>/<key>` means "resolve key `<key>` at Infisical path `/` + `<path>` at connect time". In `executor.execute` (and `schema.introspect` path — see `_ask_pipeline`/`planner.plan` call sites that connect), before `provider.connect(connection)`:

```python
async def _resolve_secrets(connection: Connection, secrets: SecretsProvider) -> Connection:
    resolved = dict(connection.settings)
    changed = False
    for k, v in resolved.items():
        if isinstance(v, str) and v.startswith("secret://"):
            provider, rest = v[len("secret://"):].split("/", 1)
            path, _, key = rest.rpartition("/")
            val = await secrets.get_secret(SecretRef(provider=provider, name=key))
            resolved[k] = val.value
            changed = True
    if not changed:
        return connection
    from dataclasses import replace
    return replace(connection, settings=resolved)
```

- [ ] **Step 1: Write the failing test**

```python
# tests/test_infisical.py
class TestInfisicalSecretsProvider(unittest.TestCase):
    def test_get_secret_uses_universal_auth(self):
        import asyncio
        from unittest import mock
        from datahek.defaults.infisical import InfisicalSecretsProvider
        from datahek.contracts.secrets import SecretRef

        provider = InfisicalSecretsProvider(host="https://infisical.test", client_id="cid",
                                            client_secret="csec", project_id="pid")
        with mock.patch("httpx.AsyncClient.post", ...) as post, \
             mock.patch("httpx.AsyncClient.get", ...) as get:
            post.return_value.json.return_value = {"accessToken": "tok"}
            get.return_value.json.return_value = {"secretValue": "sup3r"}
            val = asyncio.run(provider.get_secret(SecretRef(provider="infisical", name="pg_password")))
        self.assertEqual(val.value, "sup3r")
        # assert Authorization header used "tok" and URL contains /api/v3/secrets/raw/pg_password

    def test_executor_resolves_secret_refs(self):
        # build a Connection with settings={"password": "secret://infisical/creds/pg_password"},
        # fake SecretsProvider returning "sup3r"; call _resolve_secrets; assert resolved settings
```

- [ ] **Step 2: Run → FAIL** (`ModuleNotFoundError`)
- [ ] **Step 3: Implement** `infisical.py` + `_resolve_secrets` + call it in `executor.execute` before `provider.connect` (and in `defaults/datasets.py` runner path if it connects — reuse the same helper)
- [ ] **Step 4: Run → PASS** (unit tests + full suite)
- [ ] **Step 5: Commit** `feat: InfisicalSecretsProvider + secret:// resolution`

---

### Task 7: Infisical-backed auth users & LLM config at startup

**Files:**
- Modify: `src/datahek/defaults/auth.py`
- Modify: `src/datahek/defaults/models.py` (already touched in Task 5)
- Modify: `src/datahek/defaults/container.py`
- Test: `tests/test_infisical_auth.py`

**Interfaces:**
- Consumes: `InfisicalSecretsProvider` (Task 6)
- Produces:
  - `LocalAuthProvider.from_infisical(secrets: SecretsProvider, secret_path: str = "auth")` classmethod — loads `users` JSON from Infisical secret `datahek_users` at path `/auth` (fallback: env `DATAHEK_AUTH_LOCAL_USERS` when Infisical unconfigured or secret missing)
  - `OpenAICompatibleModelProvider.from_infisical(secrets)` — resolves `llm_base_url`, `llm_api_key`, `llm_model` secrets at path `/llm`, falls back to env

**Behavior:** container composition order: if `InfisicalSecretsProvider.is_configured()` → `AuthProvider = LocalAuthProvider.from_infisical(...)` and the LLM provider built with Infisical values; `SecretsProvider` registered as the Infisical implementation. Unchanged otherwise.

- [ ] **Step 1: Write the failing tests** — mock `get_secret` returning a JSON users string; assert `authenticate("datahek", "datahek")` works from Infisical-loaded users; assert env fallback when secrets provider is `EnvSecretsProvider`.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** both classmethods + container wiring
- [ ] **Step 4: Run → PASS** (existing `tests/test_auth.py` must stay green)
- [ ] **Step 5: Commit** `feat: Infisical-backed auth users and LLM config`

---

### Task 8: Container wiring, docker-compose services, docs

**Files:**
- Modify: `src/datahek/defaults/container.py`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `README.md` (Configuration table + "Persistent metadata" section)
- Modify: `pyproject.toml` (redis + crypto extras already added in Tasks 2/5)
- Test: `tests/test_container_selection.py`

**Behavior (exact selection logic in `build_app_container`):**
```python
pg = PgMetadata()                      # reads DATAHEK_METADATA_URL
if pg._url:
    await-less wiring: ConnectionManager = PostgresConnectionManager(pg, encryption_key=os.environ.get("DATAHEK_ENCRYPTION_KEY"))
    ConversationStore = PostgresConversationStore(pg)
    PromptStore = PostgresPromptStore(pg)
    EvaluationStore = PostgresEvaluationStore(pg)
if metadata_config().redis_url:
    store = RedisLlmSettingsStore(url=metadata_config().redis_url)
    c.register(RedisLlmSettingsStore, store, singleton=True)
    model_provider = OpenAICompatibleModelProvider(settings_store=store)
```
(`init_schema()` is called once at API startup inside `create_app` via a lifespan hook or lazy `async` first-use — prefer lazy init in each store's first query with a module-level `_initialized` guard; simplest: call `await pg.init_schema()` in `create_app` before returning `app`.)

**docker-compose.yml additions (top-level `services:`):**
```yaml
  postgres:
    image: postgres:16-alpine
    container_name: datahek-oss-postgres
    environment:
      POSTGRES_USER: datahek
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-datahek}
      POSTGRES_DB: datahek
    ports: ["5433:5432"]
    volumes: [datahek-pg:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U datahek"]
      interval: 5s
      timeout: 3s
      retries: 10
  redis:
    image: redis:7-alpine
    container_name: datahek-oss-redis
    ports: ["6380:6379"]
    volumes: [datahek-redis:/data]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
```
`api` service gains `depends_on: [postgres, redis]` (condition: service_healthy) and env `DATAHEK_METADATA_URL: postgresql://datahek:${POSTGRES_PASSWORD:-datahek}@postgres:5432/datahek` + `DATAHEK_METADATA_REDIS_URL: redis://redis:6379/0`. Volumes `datahek-pg`, `datahek-redis` added to the volumes section. (Existing SQLite default remains for those who don't set the URLs.)

**.env.example additions:** `DATAHEK_METADATA_URL=`, `DATAHEK_METADATA_REDIS_URL=`, `DATAHEK_ENCRYPTION_KEY=`, `INFISICAL_HOST=`, `INFISICAL_CLIENT_ID=`, `INFISICAL_CLIENT_SECRET=`, `INFISICAL_PROJECT_ID=`.

- [ ] **Step 1: Write the failing test** — build container with env vars set (monkeypatch `os.environ`), assert resolved interfaces are the PG/Redis implementations; assert defaults still resolve to SQLite/in-memory without env.
- [ ] **Step 2: Run → FAIL** (wiring absent)
- [ ] **Step 3: Implement** container selection + `create_app` schema init + compose + env example + README
- [ ] **Step 4: Run → PASS** — full suite (257 existing + new), then live: `docker compose up -d --build`, restart API twice, verify a connection + conversation + LLM settings survive the second restart.
- [ ] **Step 5: Commit** `feat: env-driven persistent metadata (PG+Redis) and Infisical secrets`

---

### Task 9: Live verification & cleanup

**Files:** none (verification only)

- [ ] **Step 1:** With compose up: create connection via API → restart API → `GET /connections` still lists it (persistence proof)
- [ ] **Step 2:** `POST /settings/llm {"model":"x"}` → restart API → `GET /settings/llm` returns `x` (Redis proof)
- [ ] **Step 3:** Configure `INFISICAL_*` in `.env` (test instance) → start API → verify auth login works from Infisical users and a `secret://infisical/...` connection resolves at ask time (Infisical proof)
- [ ] **Step 4:** Confirm no plaintext secrets in: API responses, audit JSONL, PG `connections.settings_json` (encrypted when key set)
- [ ] **Step 5:** Update README quick-start if compose instructions changed; final `python -m unittest discover tests` green
- [ ] **Step 6:** Commit any doc touch-ups