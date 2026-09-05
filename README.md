<div align="center">

# DataHek OSS

**Universal conversational data platform** — connect any data source, ask questions in natural language, get safe, explained answers.

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-206%20passing-brightgreen.svg)](#testing)
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

- **Universal data engine** — a provider-agnostic **Logical Query Plan** compiled per connector (ClickHouse and PostgreSQL today); no provider-specific logic in the core
- **Read-only by construction** — Write plan nodes are structurally separated and denied before any provider runs
- **Typed guardrail decisions** — `ALLOW / DENY / REDACT / MASK / REQUIRE_APPROVAL / RATE_LIMIT` with a deterministic pipeline (input → plan → SQL → output)
- **Masking before reasoning** — sensitive columns (schema tags) are masked before the explanation model sees results; answers are PII-redacted
- **Full audit** — every guardrail decision and execution recorded with actor, tenant, and decision
- **Four surfaces, one pipeline** — REST API, CLI, MCP server, and web UI all run the same RequestContext → guardrails → audit path (MCP is never a privileged bypass)
- **Conversational memory** — multi-turn conversations persisted in SQLite with a streaming explanation endpoint
- **Evaluation** — every execution scored (validity, safety, latency) + curated offline regression datasets with `POST /evaluations/run`
- **OSS entitlements** — limits (connections ≤ 5, MCP ≤ 3, prompts ≤ 3) enforced through a replaceable `EntitlementProvider` — the path to Production/Enterprise tiers
- **Tenant-aware by construction** — every model carries `org_id`/`project_id`; OSS runs a single implicit default tenant
- **Zero core dependencies** — the kernel is stdlib-only; connectors, model providers, and the API are optional extras

---

## 📋 Requirements

- Python **3.12+**
- A clickhouse-connect/psycopg-supported database (or any future connector)
- An OpenAI-compatible LLM endpoint for the planner/reasoner (default: opencode, `mimo-v2.5`)

## 🚀 Installation

```bash
# full install (API + CLI + MCP + connectors)
pip install "datahek-core[all]"

# or minimal, adding extras as needed
pip install datahek-core
pip install "datahek-core[api,clickhouse,llm]"
```

## ⚡ Quick start

```bash
# 1. configure the LLM (any OpenAI-compatible endpoint)
export LLM_BASE_URL=https://opencode.ai/zen/go/v1
export LLM_API_KEY=your-key
export LLM_MODEL=mimo-v2.5

# 2. run the API
uvicorn datahek.api.app:create_app --factory --port 8000
# docs: http://localhost:8000/docs · web UI: http://localhost:8000

# 3. add a connection
curl -X POST http://localhost:8000/connections \
  -H "content-type: application/json" \
  -d '{"name":"ch1","provider":"clickhouse","host":"localhost","port":8123,"database":"default","settings":{"username":"default","password":"secret"}}'

# 4. ask a question
curl -X POST http://localhost:8000/ask \
  -H "content-type: application/json" \
  -d '{"question":"What is the error count by service in the traces table?","connection_id":"<conn-id>"}'
# → {"answer":"payment-api has the most errors...","rows":[{...}],...}
```

### CLI

```bash
datahek connections
datahek ask "which service has the most errors?" --connection ch1
datahek interactive
```

### MCP server

```bash
python -m datahek.mcp_server                     # streamable HTTP on :8001
claude mcp add data-vault --transport http http://localhost:8001/mcp
```

### Docker

```bash
docker compose up -d --build   # api :8000 · mcp :8001 · state in a volume
```

## 🔧 Configuration

| Variable | Default | Purpose |
|---|---|---|
| `LLM_BASE_URL` | `https://opencode.ai/zen/go/v1` | OpenAI-compatible chat endpoint |
| `LLM_API_KEY` | — | Endpoint API key |
| `LLM_MODEL` | `mimo-v2.5` | Model identifier |
| `DATAHEK_DB_PATH` | `datahek.db` | SQLite conversation store |
| `DATAHEK_AUDIT_PATH` | `datahek-audit.jsonl` | Audit trail (JSONL) |
| `DATAHEK_AUTH_MODE` | `none` | `none` or `local` (enforce API keys) |
| `DATAHEK_AUTH_LOCAL_USERS` | `{}` | JSON `{"user":"password"}` for local auth |

## 🧠 How it works

```
                    ┌──────────────────────────────┐
                    │  Experience plane             │
                    │  API · CLI · MCP · Web UI     │
                    └──────────────┬───────────────┘
                                   │ RequestContext (tenant-aware)
                    ┌──────────────▼───────────────┐
                    │  Engine (ADR-003)            │
                    │  schema → plan → guardrails  │
                    │  → audit → execute → mask    │
                    └──────────────┬───────────────┘
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
       ClickHouse connector  PostgreSQL connector  (next: more)
```

| Component | Path |
|---|---|
| Platform kernel | `datahek/kernel/` — config, ids, context, errors, events, DI, entitlements |
| Contracts (Enterprise extension points) | `datahek/contracts/` — auth, tenancy, policy, audit, secrets, providers, guardrails, models, reasoner, evaluation |
| Engine | `datahek/engine/` — LogicalPlan, guardrails, executor, masking, planner, reasoner, schema, compile |
| OSS defaults | `datahek/defaults/` — local auth/policy/tenancy, JSONL audit, SQLite conversations, OpenAI-compatible model, evaluator, dataset runner |
| Connectors | `datahek/connectors/` — ClickHouse, PostgreSQL |
| Surfaces | `datahek/api/` (FastAPI + web UI), `datahek/cli.py`, `datahek/mcp_server.py` |

## 🧪 Testing

```bash
python -m unittest discover tests -v   # 206 tests
```

Coverage: kernel foundations, contracts conformance, logical plans, guardrails, engine (audit/masking/evaluation), schema discovery, planner, reasoner, conversations, auth, entitlements, API, CLI, MCP, streaming, web UI, datasets, both connectors.

## 🗺️ Roadmap

- ✅ Platform kernel + contracts · vertical slice (ClickHouse) · API/CLI/MCP/web surfaces · streaming · conversations · reasoner · evaluation + datasets · masking · entitlements · PostgreSQL connector · Docker
- 🔜 CI · PostgreSQL real-data E2E · additional connectors (MySQL, SQLite) · semantic layer · visualization engine
- 🔒 **Enterprise** (separate repo): SSO/SCIM, multi-tenancy, policy engine, centralized audit, admin console — built as implementations of the OSS contracts

## 🤝 Contributing

1. Fork the repository.
2. Create a feature branch (`git checkout -b feat/my-feature`).
3. Write tests first for any behavior change (`python -m unittest tests.test_xxx`).
4. Run the full suite (`python -m unittest discover tests`) — keep it green.
5. Open a pull request describing the change and the tests.

All contributions to OSS packages are licensed under Apache-2.0 (DCO).

## ❓ FAQ / Troubleshooting

| Problem | Fix |
|---|---|
| `/ask` returns `429 RATE_LIMITED` | Your LLM endpoint is rate-limited — retry later or switch `LLM_BASE_URL`/`LLM_MODEL` |
| `/ask` returns `502 CONNECTION_FAILED` | Schema discovery failed — check the connection host/port/credentials |
| Connections reach the limit | OSS default is 5 per project; override `EntitlementProvider` in your composition for more |
| I want auth | Set `DATAHEK_AUTH_MODE=local` and `DATAHEK_AUTH_LOCAL_USERS='{"admin":"secret"}'`, then send `X-API-Key` |
| The web UI shows no connections | Add one in the sidebar (host/port/database) and select it |

## 📄 License

[Apache-2.0](LICENSE) — © 2026 Abdul-Jaweed. Enterprise modules (separate repository) are proprietary; see the licensing ADR for the open-core boundary.

## 🙏 Acknowledgements

Built on [LangGraph/LangChain](https://github.com/langchain-ai) ecosystem patterns, [sqlglot](https://github.com/tobymao/sqlglot), [FastMCP](https://github.com/jlowin/fastmcp), [FastAPI](https://fastapi.tiangolo.com/), and [ClickHouse](https://clickhouse.com/) — with architectural guidance from the open-core review (see `docs/v2/` in the parent project).