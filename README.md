# DataHek OSS

**Universal conversational data platform — v0.2.0**

Connect any data source. Ask questions in natural language. DataHek discovers the schema, plans a read-only query, validates it through guardrails, executes it safely, and explains the results — across an API, CLI, and MCP server.

```
question → schema discovery → logical plan → validation → guardrails
         → audit → execution → masking → explanation → conversation
```

---

## Quick start

```bash
# install (all extras)
uv pip install -e ".[all]"

# run the API
uvicorn datahek.api.app:create_app --factory --port 8000
# docs: http://localhost:8000/docs

# or the CLI
datahek connections
datahek ask "which service has the most errors?" --connection ch1
datahek interactive

# or the MCP server (HTTP on :8001)
python -m datahek.mcp_server
```

### Configuration (env)

| Variable | Default | Purpose |
|---|---|---|
| `LLM_BASE_URL` | `https://opencode.ai/zen/go/v1` | OpenAI-compatible chat endpoint |
| `LLM_API_KEY` | — | API key for the endpoint |
| `LLM_MODEL` | `mimo-v2.5` | Model identifier |
| `DATAHEK_DB_PATH` | `datahek.db` | SQLite conversation store |
| `DATAHEK_AUDIT_PATH` | `datahek-audit.jsonl` | Audit trail |

### Docker

```bash
docker compose up -d --build
# api :8000 · mcp :8001 — state in the datahek-data volume
```

---

## Architecture

```
packages/datahek-core (this repo) — v0.2.0
├── kernel/       contracts foundations: config, ids, RequestContext, errors,
│                 events, capabilities, DI container, entitlements
├── contracts/    stable interfaces Enterprise implements without forking:
│                 auth, tenancy, policy, audit, secrets, connections,
│                 providers, guardrails, models, reasoner, evaluation, storage
├── engine/       universal data engine (ADR-003):
│                 LogicalPlan → validation → guardrails → execution →
│                 masking → normalized results; planner + reasoner
├── defaults/     OSS implementations: local auth/policy/tenancy, JSONL audit,
│                 env secrets, SQLite conversations, OpenAI-compatible model,
│                 evaluator, masking policy, service container
├── connectors/   ClickHouse provider (schema introspection, plan→SQL compile)
└── api/ cli/ mcp_server.py   experience plane (same pipeline, no bypass)
```

### Security model

- **Read-only by construction** — Write plan nodes are structurally separated and denied by the guardrail pipeline before any provider runs
- **Typed guardrail decisions** — `ALLOW / DENY / REDACT / MASK / REQUIRE_APPROVAL / RATE_LIMIT`
- **Masking before reasoning** — sensitive columns (schema `semantic_tags`) are masked before the explanation model sees results; answers are PII-redacted
- **Full audit** — every guardrail decision and execution is recorded with actor, tenant, and decision
- **Sanitized errors** — driver internals never leak; unexpected failures return a generic `INTERNAL`

### Tenancy

Every model is tenant-aware (`org_id`/`project_id`) by construction; OSS runs a single implicit `default` organization/project. Enterprise replaces `TenantContext`/stores via the container — no core changes.

---

## API

| Endpoint | Purpose |
|---|---|
| `GET /health` | version, capabilities, entitlements, providers |
| `POST/GET /connections` | create/list connections |
| `POST /ask` | question → plan → execute → explain (`answer`, `rows`) |
| `POST/GET /conversations` | multi-turn conversations (turns recorded on ask) |
| `GET /evaluations` | execution scores + aggregate pass rate |

Errors: `{code, message, details}` with typed codes (`CONNECTION_NOT_FOUND`, `QUERY_DENIED`, `CONNECTION_FAILED`, …).

## MCP tools

| Tool | Purpose |
|---|---|
| `data.list_tables(connection)` | tables with row counts |
| `data.table_schema(connection, table)` | columns with types |
| `data.ask(question, connection)` | full pipeline with explanation |

## CLI

```
datahek connections
datahek ask "<question>" --connection <name-or-id>
datahek interactive
```

## Tests

```bash
python -m unittest discover tests -v   # 163 tests
```

Coverage: kernel foundations, services, contracts/defaults conformance, logical plans, guardrails, engine (audit, masking, evaluation), schema discovery, planner, reasoner, conversations, API, CLI, MCP, masking.

## Roadmap (per docs/v2)

- ✅ Platform kernel + contracts
- ✅ Vertical slice (ClickHouse)
- ✅ API + CLI + MCP surfaces
- ✅ Conversations (SQLite) · reasoner · evaluation hooks · masking
- 🔜 Docker packaging polish · docs · CI
- 🔜 PostgreSQL connector (proves connector generality)
- 🔜 Enterprise extensions (private repo): SSO, tenancy, policy engine, centralized audit

## License

Apache-2.0 (OSS packages). Enterprise modules are proprietary — see the licensing ADR.