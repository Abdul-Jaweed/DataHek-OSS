# ADR-003: PostgreSQL metadata store

**Status:** Accepted (implemented)

## Context

DataHek persists platform metadata: connections, conversations and messages, prompt templates,
metric definitions, evaluation runs, approvals, and checkpoints. OSS must run with zero external
dependencies; Enterprise must run with durable, shared storage.

## Decision

Use **PostgreSQL for durable platform metadata**, selected automatically when
`DATAHEK_METADATA_URL` is set. When it is not set, OSS falls back to local SQLite
(`DATAHEK_DB_PATH`, default `datahek.db`).

Both backends implement the same contracts (`ConnectionManager`, `ConversationStore`,
`PromptStore`, `SemanticStore`, `ApprovalService`, `CheckpointStore`, `EvaluationStore`).

## Why this decision

- PostgreSQL gives Enterprise the transactional, multi-worker, tenant-aware store the control plane
  needs (org/project columns on every table).
- SQLite keeps the OSS quickstart dependency-free — clone, run, ask a question.
- One repository pattern with two interchangeable implementations preserves the OSS/Enterprise
  boundary without forking logic.

## Alternatives considered

1. Files only (JSON/JSONL) for everything.
2. SQLite only, promoted to PostgreSQL later with a migration project.

## Why alternatives were rejected

- Files: no transactions, unsafe for concurrent workers, no query surface for audit-scale data.
- SQLite only: the eventual PostgreSQL migration was already identified as painful in the
  foundation review; supporting both behind contracts from the start avoids a rewrite.

## Consequences

- `datahek/defaults/pg.py` owns connection handling and schema initialization for all PG stores
  (`connections`, `conversations`, `messages`, `prompts`, `evaluation_runs`, `approvals`,
  `checkpoints`, plus semantic metrics).
- Versioned migrations are implemented in `defaults/pg.py`: an ordered `_MIGRATIONS` list tracked in
  the `schema_migrations` table, applied at startup under a PostgreSQL advisory lock. Migration 1 is
  the idempotent baseline schema, so databases created before migration tracking are adopted in
  place. Add new schema changes as new numbered migrations — never edit an applied migration.
- Connection credentials in PostgreSQL can be encrypted at rest via `DATAHEK_ENCRYPTION_KEY`
  (Fernet). See ADR-013.

## Migration strategy

SQLite → PostgreSQL is a data export/import exercise; both stores share the same contracts and
row shapes. No dual-write mode exists.

## Revisit conditions

- Migration tooling (Alembic or equivalent) becomes necessary once schema evolution starts.
- A deployment requires a store other than SQLite/PostgreSQL (for example MySQL) — a new contract
  implementation, not a new pattern.
