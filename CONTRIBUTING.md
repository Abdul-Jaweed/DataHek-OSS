# Contributing to DataHek OSS

DataHek OSS is the open-source core of the DataHek platform (Apache-2.0). Enterprise capabilities
are built in a separate repository as implementations of the contracts in this one. This guide
covers setup, the conventions the codebase follows, and the process for landing changes.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[all]"
python -m unittest discover tests                    # full suite
uvicorn datahek.api.app:create_app --factory --port 8000
```

Frontend: `cd apps/web && npm install && npm run dev` (Vite proxies the API on :8000).
Full stack: `docker compose up -d --build` serves the production web build; use
`docker compose --profile dev up web-dev` for the hot-reload dev server in Docker.

## Before you start

- **Read the ADRs.** Architecture decisions live in [`docs/adr/`](docs/adr/README.md). Major
  features and boundary changes need an ADR before implementation, following the baseline sections:
  Context / Decision / Why this decision / Alternatives considered / Why alternatives were rejected /
  Consequences / Migration strategy / Revisit conditions.
- **Respect the OSS/Enterprise boundary.** OSS must build, test, and run without the Enterprise
  repository. Enterprise attaches through the DI container and extension registry — never through
  scattered edition checks. Edition differences come from `kernel/capabilities.py` and the
  entitlement layer.
- **Safety stays in OSS.** Read-only enforcement, SQL/plan validation, guardrails, basic audit,
  approvals, and masking are never plan-gated.

## Naming and conventions

### Python

- PEP 8: `snake_case` modules and functions, `PascalCase` classes, `UPPER_SNAKE` constants.
- **Contracts** (`src/datahek/contracts/`): one domain per module, Protocols plus their DTOs.
  `misc.py` is frozen — new contracts get their own module.
- **Default implementations** (`src/datahek/defaults/`) are named by storage/locality prefix:

  | Prefix | Meaning |
  | --- | --- |
  | `Local*` | in-process / in-memory default |
  | `Sqlite*` | SQLite-backed (default durable store) |
  | `Postgres*` | PostgreSQL-backed |
  | `Env*` / `Infisical*` | secret sources |
  | `Jsonl*` / `Redis*` | file- / Redis-backed infrastructure |

- **Postgres variants** of an existing store live in `<domain>_pg.py` (for example
  `conversations_pg.py`) next to the default `<domain>.py`.
- **Connectors** are `{Product}Provider`: `ClickHouseProvider`, `PostgresProvider`, `MySQLProvider`,
  `SQLiteProvider`, `DuckDBProvider`. The `Sqlite` / `Postgres` spellings in `defaults/` are the
  established forms — do not rename existing classes in unrelated PRs; bulk renames are their own
  change with their own justification.
- **Error codes**: `UPPER_SNAKE` members of `ErrorCode`; HTTP mapping stays in `_STATUS_BY_CODE`.
- **Audit events**: `<domain>.<action>` lowercase — `connection.create`, `auth.failure`,
  `approval.decision`, `guardrail.decision`, `query.execution`, `mcp.tool`. Decisions use the typed
  vocabulary (`ALLOW` / `DENY` / `REDACT` / `MASK` / `REQUIRE_APPROVAL` / `RATE_LIMIT`), stored
  uppercase.
- **Environment variables**: `DATAHEK_*` for platform behavior, vendor prefixes for third-party
  config (`LLM_*`, `INFISICAL_*`). Limits are configurable defaults, never hard restrictions.

### API

- REST paths are lowercase and plural (`/connections`, `/saved-queries`, `/semantics`); verbs only
  for genuine actions (`/ask`, `/approvals/{id}/decide`).
- `201` for creates, `202` for approval-required, `204` for deletes; everything else maps through
  `_STATUS_BY_CODE`.

### Frontend (`apps/web`)

- Pages are `PascalCase.tsx` under `src/features/`; primitives are lowercase under
  `src/components/ui/`.
- Use design tokens, never raw hex in components; merge classes with `cn()`; icons come from
  Phosphor only.

### Tests (`tests/`)

- `tests/test_<subject>.py`, `unittest.TestCase`; async code runs through `asyncio.run`.
- Postgres/Redis-backed tests are environment-gated (`DATAHEK_TEST_PG_URL`,
  `DATAHEK_TEST_REDIS_URL`) and must skip cleanly when the service is absent.

### Documentation

- ADRs: `docs/adr/ADR-NNN-kebab-title.md`; update the index when adding one.
- Keep README claims true (test counts, connector list, config table). `docs/` is local-only except
  `docs/adr/` — do not commit other docs.

## Commits and pull requests

- Conventional commit subjects: `feat`, `fix`, `chore`, `docs`, `test`, `style`, `refactor`.
- Every behavior change ships with tests; run `python -m unittest discover tests` before opening a
  PR (frontend changes: `npx tsc --noEmit && npm run build`).
- Never commit runtime state (`datahek.db`, `*.jsonl`), secrets, or `.env`.

All contributions to OSS packages are licensed under Apache-2.0. By contributing you agree your
work may be distributed under that license.
