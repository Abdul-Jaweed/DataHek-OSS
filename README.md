<div align="center">

# DataHek OSS

**Universal conversational data platform** — connect any data source, ask questions in natural language, get safe, explained answers.

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-475%20passing-brightgreen.svg)](#testing)
[![Version](https://img.shields.io/badge/version-0.2.0-orange.svg)](https://github.com/Abdul-Jaweed/DataHek-OSS)
[![MCP](https://img.shields.io/badge/MCP-fastmcp-38BDF8.svg)](#mcp-server)

</div>

DataHek OSS turns natural language into **safe, read-only data operations**. It discovers your schema, plans a query, validates it through a guardrail pipeline, executes it, and explains the results — across a REST API, a CLI, an MCP server, and a web UI.

```
question → schema discovery → logical plan → validation → guardrails
         → audit → execution → masking → explanation → conversation
```

> **One engine. OSS for everyone. Enterprise for the org.** — the open-source core of the DataHek platform; Enterprise adds SSO, multi-tenancy, policy engines, and centralized audit as extensions over the same contracts.

---

## ✨ Key features

- **Universal data engine** — a provider-agnostic **Logical Query Plan** with **multi-table JOINs** (AST-level join model, join tables validated and policy-checked), compiled per connector (ClickHouse, PostgreSQL, MySQL, SQLite, DuckDB)
- **Read-only by construction** — write plans are structurally denied before any provider runs
- **Typed guardrail decisions** — `ALLOW / DENY / REDACT / MASK / REQUIRE_APPROVAL / RATE_LIMIT` across input → plan → SQL → output
- **Masking before reasoning** — sensitive columns are masked before the explanation model sees results
- **Full audit** — every guardrail decision and execution recorded with actor, tenant, and decision
- **Dual-layer read-only** — AST validation plus *physical* enforcement: PG `default_transaction_read_only`, SQLite `mode=ro`, MySQL read-only sessions, ClickHouse `readonly=1`
- **Human-in-the-loop approvals** — large exports, unbounded scans, and sensitive tables pause for approval (`/approvals`, UI inbox) before executing
- **Checkpoints & replay** — every run is stored (`/checkpoints`); replay re-executes a stored plan deterministically, no LLM involved
- **Independent verification** — a verifier model checks the result answers the question, without seeing the planner's reasoning
- **Observability** — Prometheus-compatible `GET /metrics` (requests, durations, ask outcomes, rows) and optional JSON logs (`DATAHEK_LOG_FORMAT=json`)
- **Saved & scheduled queries** — save recurring questions, run them any time, schedule them (in-process scheduler; every run goes through the full guarded pipeline)
- **Checkpoint fork & diff** — re-plan a stored question as a new lineage; compare any two runs field by field
- **Audit search** — `GET /audit` filters the JSONL trail by event type, actor, decision, or free text
- **Catalog-aware skills** — domain guidance (time-series, debugging) only activates when the schema actually has matching columns
- **MCP per-client tokens** — optional bearer auth with scopes (`DATAHEK_MCP_TOKENS`)
- **7 MCP tools** — list_tables · table_schema · ask · list_connections · list_metrics · run_saved_query (deterministic replay when possible) · replay_checkpoint
- **Follow-up suggestions** — opt-in agent proposing next questions (`DATAHEK_SUGGESTIONS=on`); clicking a chip asks it
- **Semantic layer** — named metric definitions (`revenue = sum(amount) on orders`) stored in the catalog; the planner prefers them over guessing column semantics
- **Charts & export** — numeric results render as bar/line charts (with a table toggle) and every result table exports to CSV
- **Multi-step analysis** — complex questions are decomposed into sub-queries, each executed through the same guarded pipeline, then synthesized into one answer (`DATAHEK_ANALYST=off` to disable)
- **Rate limiting** — per-user sliding-window limiter protects the LLM budget
- **Perimeter guardrails** — input injection/write-intent signatures and length/control-char checks before the LLM; output scanner strips emails, phones, cards, SSNs, API keys, tokens, passwords, and connection strings from every answer
- **Four surfaces, one pipeline** — REST API, CLI, MCP server, and web UI share the same guardrails (MCP is never a privileged bypass)
- **Conversational memory** — multi-turn conversations persisted in SQLite with streaming answers; recent turns feed the planner, so follow-ups like *"now the same but only for errors"* resolve correctly
- **Local authentication** — `POST /auth/login` (default user `datahek`/`datahek`), enforced via `X-API-Key`
- **Skills & prompts** — keyword-triggered domain guidance and up to 3 custom planner templates
- **Evaluation** — every execution scored (validity, safety, latency) + regression datasets
- **Tenant-aware by construction** — every model carries `org_id`/`project_id`; OSS runs a single implicit tenant
- **LLM-agnostic** — any OpenAI-compatible endpoint, configured at runtime from the web UI

---

## 📋 Requirements

- **Docker** (recommended) — for the containerized quick start
- Or Python **3.12+** with a virtual environment — to run from source
- A ClickHouse, PostgreSQL, MySQL, SQLite, or DuckDB database
- An OpenAI-compatible LLM endpoint (configured in the web UI, or via environment)

---

## 🚀 Quick start

### Option A — Docker (recommended)

```bash
# 1. clone
git clone https://github.com/Abdul-Jaweed/DataHek-OSS.git
cd DataHek-OSS

# 2. configure your LLM endpoint (optional — the web UI has a Settings form too)
cp .env.example .env        # then edit LLM_BASE_URL / LLM_API_KEY / LLM_MODEL

# 3. build & start
docker compose up -d --build

# 4. open the app
# API docs: http://localhost:8000/docs · web app: cd apps/web && npm install && npm run dev → http://localhost:5173
```

| Service | Port | Purpose |
|---|---|---|
| `api` | `8000` | REST API, `/docs`, health at `/health` |
| `mcp` | `8001` | MCP endpoint at `/mcp` |

- SQLite state and the audit log persist in the `datahek-data` volume.
- Useful commands: `docker compose logs -f api` · `docker compose down` (keeps data) · `docker compose down -v` (wipes data).

### Option B — Run from source

```bash
git clone https://github.com/Abdul-Jaweed/DataHek-OSS.git
cd DataHek-OSS

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[all]"

# configure the LLM endpoint (any OpenAI-compatible service)
export LLM_BASE_URL=...          # optional — the web UI Settings form can set it at runtime
export LLM_API_KEY=...
export LLM_MODEL=...

uvicorn datahek.api.app:create_app --factory --port 8000
```

> The `datahek-core` package is **not published to PyPI yet** — install from source as above.

### First steps in the UI

1. Open the web app → **Settings** → enter your **LLM base URL, API key, and model** → Save.
2. **Connections** → add your database (provider, host, port, database, credentials, SSL).
3. **Chat** → ask anything, e.g. *"How many rows are in the traces table?"*

### API (curl)

```bash
# add a connection
curl -X POST http://localhost:8000/connections \
  -H "content-type: application/json" \
  -d '{"name":"ch1","provider":"clickhouse","host":"localhost","port":8123,"database":"default","settings":{"username":"default","password":"secret"}}'

# test a connection as-entered (nothing persisted)
curl -X POST http://localhost:8000/connections/test \
  -H "content-type: application/json" \
  -d '{"name":"ch1","provider":"clickhouse","host":"localhost","port":8123,"database":"default","settings":{"username":"default","password":"secret"}}'

# ask a question
curl -X POST http://localhost:8000/ask \
  -H "content-type: application/json" \
  -d '{"question":"What is the error count by service in the traces table?","connection_id":"<conn-id>"}'
```

With `DATAHEK_AUTH_MODE=local`, log in first and send the token:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "content-type: application/json" -d '{"username":"datahek","password":"datahek"}'
curl -X POST http://localhost:8000/ask -H "X-API-Key: datahek" \
  -H "content-type: application/json" -d '{"question":"...","connection_id":"<conn-id>"}'
```

### CLI & MCP

```bash
datahek connections
datahek ask "which service has the most errors?" --connection ch1
datahek interactive

python -m datahek.mcp_server    # streamable HTTP on :8001
```

---

## 🔧 Configuration

| Variable | Default | Purpose |
|---|---|---|
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | env or UI Settings | OpenAI-compatible endpoint (the web UI form overrides at runtime) |
| `DATAHEK_DB_PATH` | `datahek.db` | SQLite conversation store |
| `DATAHEK_AUDIT_PATH` | `datahek-audit.jsonl` | Audit trail (JSONL) |
| `DATAHEK_AUTH_MODE` | `none` | `none` or `local` (enforce API keys) |
| `DATAHEK_AUTH_LOCAL_USERS` | `{"datahek":"datahek"}` | JSON `{"user":"password"}` for local auth |
| `DATAHEK_APPROVAL_ROW_LIMIT` | `1000` | Row limit (or unbounded scan) that requires human approval |
| `DATAHEK_APPROVAL_SENSITIVE_TABLES` | credential/password/pii patterns | Comma-separated table-name patterns that require approval |
| `DATAHEK_RATE_LIMIT_PER_MINUTE` | `120` | Per-user request limit (sliding window) |
| `DATAHEK_VERIFIER` | `on` | Independent post-execution answer verification (`off` to disable) |
| `DATAHEK_GUARDRAIL_INPUT` | `on` | Input injection/length checks (`off` to disable) |
| `DATAHEK_MASK_MODE` | `redact` | Sensitive-column masking strategy: `redact` · `hash` · `partial` |
| `DATAHEK_MASK_SALT` | `datahek` | Salt for the `hash` masking strategy |
| `DATAHEK_MCP_TOOL_TIMEOUT` | `120` | Seconds before an MCP tool call is stopped |
| `DATAHEK_MCP_TOKENS` | *(empty)* | Per-client MCP bearer tokens (`token,other:scopeA\|scopeB`); empty disables MCP auth |
| `DATAHEK_MCP_REQUIRED_SCOPES` | *(empty)* | Scopes every MCP token must carry when MCP auth is enabled |
| `DATAHEK_MCP_TOOL_SCOPES` | *(empty)* | Per-tool scopes (`data.ask:ask,data.replay_checkpoint:replay\|audit`); denied calls are audited |
| `DATAHEK_SCHEDULER_POLL_SECONDS` | `30` | Scheduler tick interval for saved-query schedules |
| `DATAHEK_DEFAULT_LIMIT` | `10` | Fallback SQL `LIMIT` when the planner does not specify one |
| `DATAHEK_LOG_FORMAT` | `text` | `json` emits one structured log object per line |
| `DATAHEK_SUGGESTIONS` | `off` | `on` = propose follow-up questions after each answer |
| `DATAHEK_MAX_QUESTION_CHARS` | `2000` | Maximum accepted question length |
| `DATAHEK_ANALYST` | `on` | Multi-step decomposition for complex questions (`off` to disable) |
| `DATAHEK_DB_PATH` | `datahek.db` | SQLite conversation/checkpoint/metric store |
| `DATAHEK_METADATA_URL` | *(empty)* | PostgreSQL URL for durable connections/conversations/prompts/evaluations (empty → SQLite/in-memory defaults) |
| `DATAHEK_METADATA_REDIS_URL` | *(empty)* | Redis URL for LLM settings persistence across restarts (empty → runtime settings only) |
| `DATAHEK_ENCRYPTION_KEY` | *(empty)* | Optional: encrypt connection settings at rest in PostgreSQL |
| `INFISICAL_HOST` / `INFISICAL_CLIENT_ID` / `INFISICAL_CLIENT_SECRET` / `INFISICAL_PROJECT_ID` / `INFISICAL_ENVIRONMENT` | *(empty)* / `dev` | Optional: fetch secrets from Infisical (see below) |

### Persistent metadata (optional)

By default DataHek keeps state in local SQLite (`DATAHEK_DB_PATH`) and in-memory
structures. For durable, restart-proof metadata set `DATAHEK_METADATA_URL` (and
optionally `DATAHEK_METADATA_REDIS_URL`):

- **PostgreSQL** — when `DATAHEK_METADATA_URL` is set, connections,
  conversations, prompt templates, and evaluation runs are stored in
  PostgreSQL. Versioned schema migrations run automatically at API startup
  under an advisory lock and are tracked in the `schema_migrations` table
  (baseline migration 1 is idempotent, so pre-existing databases are adopted
  in place).
  `DATAHEK_ENCRYPTION_KEY` encrypts stored connection settings at rest
  (any non-empty string); without it, settings are stored as plain JSON.
  This encryption-at-rest guarantee covers PostgreSQL connection settings
  only — the Redis LLM settings store persists the API key as plaintext,
  so treat `DATAHEK_METADATA_REDIS_URL` as sensitive.
- **Redis** — when `DATAHEK_METADATA_REDIS_URL` is set, LLM settings saved via
  the UI/API (`/settings/llm`) persist across API restarts and are re-applied on
  startup.
- **Infisical** — with `INFISICAL_HOST` / `INFISICAL_CLIENT_ID` /
  `INFISICAL_CLIENT_SECRET` / `INFISICAL_PROJECT_ID` set, secrets are fetched
  from Infisical: database credentials referenced as
  `secret://infisical/<folder>/<key>` in connection settings, auth users at the
  `/auth` folder (`datahek_users`), and LLM configuration at `/llm`.

The Docker quick start already wires all of this up: `docker compose up -d
--build` starts `postgres` (port `5433`) and `redis` (port `6380`) alongside
the `api` and `mcp` services, so metadata is persistent by default in the
compose stack. Leave the URLs unset to keep the zero-dependency SQLite defaults.

> **Security note:** the development compose publishes PostgreSQL (`5433`) and
> Redis (`6380`) on localhost with default credentials (`datahek`/`datahek`,
> no Redis password). Do not expose these ports beyond localhost in shared or
> production environments.

---

## 🧠 How it works

```
┌───────────────────────────────┐
│  Experience plane             │
│  Web UI · REST API · CLI · MCP│
└──────────────┬────────────────┘
               │  RequestContext (tenant-aware)
┌──────────────▼────────────────┐
│  Data plane (ADR-006)         │
│  schema discovery → plan      │
│  → guardrails → audit         │
│  → execute → mask → explain   │
└──────────────┬────────────────┘
      ┌────────┼────────┬────────┐
      ▼        ▼        ▼        ▼
 ClickHouse PostgreSQL MySQL SQLite/DuckDB
 (connectors compile the same LogicalPlan)

Control plane (OSS baseline): connections · conversations · prompts ·
semantics · approvals · checkpoints · entitlements — all tenant-aware
```

The three planes are architectural responsibilities, not repositories: the data plane works with
data, the control plane manages the platform, and the experience plane is how users and systems
interact. Enterprise adds implementations in the control plane; it never forks the data plane.

| Component | Path |
|---|---|
| Platform kernel | `src/datahek/kernel/` — config, ids, context, errors, events, DI, capabilities, entitlements |
| Contracts (Enterprise extension points) | `src/datahek/contracts/` — auth, tenancy, policy, audit, secrets, providers, guardrails, models, reasoner, evaluation |
| Engine | `src/datahek/engine/` — LogicalPlan, guardrails, executor, masking, planner, reasoner, schema, compile |
| OSS defaults | `src/datahek/defaults/` — local auth/policy/tenancy, JSONL audit, SQLite conversations, OpenAI-compatible model, evaluator, dataset runner |
| Connectors | `src/datahek/connectors/` — ClickHouse, PostgreSQL, MySQL, SQLite, DuckDB |
| Surfaces | `src/datahek/api/` (FastAPI), `src/datahek/cli.py`, `src/datahek/mcp_server.py`, `apps/web/` (React web UI) |

---

## 📓 Notebooks

Eight executable teaching notebooks in `notebooks/` — all run **offline**
(a deterministic stub model replaces the LLM, so no API key or network is
needed):

| # | Notebook | Teaches |
|---|---|---|
| 01 | `01_quickstart` | end-to-end: ask, stream, checkpoints |
| 02 | `02_pipeline` | schema → plan → validate → guardrails → execute → explain |
| 03 | `03_guardrails` | input injection, read-only plans, dialect checks, physical sandboxing |
| 04 | `04_joins` | multi-table plans, compiled SQL, policy coverage |
| 05 | `05_approvals` | human-in-the-loop gating and decisions |
| 06 | `06_checkpoints_replay` | stored runs and deterministic replay |
| 07 | `07_semantic_layer` | metric definitions the planner prefers |
| 08 | `08_evaluation` | regression dataset and live scoring |

```bash
pip install -e ".[notebooks]"
jupyter lab notebooks/          # open any notebook
python notebooks/_build.py      # re-execute all notebooks (CI-style)
```

## 🐳 Prebuilt images (GHCR) & docs site

- **Container images**: `.github/workflows/docker.yml` (kept locally — pushing workflow files needs a `workflow`-scoped token) builds and publishes `ghcr.io/<owner>/datahek-oss` on version tags. To run from a prebuilt image, set `image: ghcr.io/abdul-jaweed/datahek-oss:latest` on the `api`/`mcp` services and `docker compose up -d` (no `--build`).
- **Docs site**: `docs-site/index.html` — deploy via Pages (branch `main`, folder `/docs-site`) or serve with `python -m http.server 8080 --directory docs-site`.

## 🧪 Testing

```bash
python -m unittest discover tests   # 475 tests
```

Coverage: kernel foundations, contracts conformance, logical plans, guardrails, engine (audit/masking/evaluation), schema discovery, planner, reasoner, conversations, auth, entitlements, API (connections, login, LLM settings), CLI, MCP, streaming, web UI, datasets, all five connectors.

---

## 👥 Development

### Contributing

1. Fork the repository.
2. Create a feature branch (`git checkout -b feat/my-feature`).
3. Write tests first for any behavior change (`python -m unittest tests.test_xxx`).
4. Run the full suite (`python -m unittest discover tests`) — keep it green.
5. Open a pull request describing the change and the tests.

All contributions to OSS packages are licensed under Apache-2.0 (DCO).

Architecture decisions are recorded as ADRs in [`docs/adr/`](docs/adr/README.md) before major
features land — see the index for what is accepted, proposed, and open.

---

## 🗺️ Roadmap

- ✅ Platform kernel + contracts · JOINs (AST join model · validation · policy coverage) · vertical slice (ClickHouse) · API/CLI/MCP/web surfaces · streaming · conversations · reasoner · evaluation + datasets · masking · entitlements · connectors (ClickHouse, PostgreSQL, MySQL, SQLite, live-verified) · Docker · local auth + login · connection test/delete · React web UI · runtime LLM settings
- 🔜 CI workflow rollout (file ready in `.github/workflows/`; needs a `workflow`-scoped token) · visualization engine · enterprise operations
- 🔒 **Enterprise** (separate repo): SSO/SCIM, multi-tenancy, policy engine, centralized audit, admin console — built as implementations of the OSS contracts

---

## 📄 License

[Apache-2.0](LICENSE) — © 2026 DataHek. Enterprise modules (separate repository) are proprietary; see [ADR-002](docs/adr/ADR-002-open-core-licensing.md) for the open-core boundary.

## 🙏 Acknowledgements

Built on [LangGraph/LangChain](https://github.com/langchain-ai) ecosystem patterns, [sqlglot](https://github.com/tobymao/sqlglot), [FastMCP](https://github.com/jlowin/fastmcp), [FastAPI](https://fastapi.tiangolo.com/), and [ClickHouse](https://clickhouse.com/).