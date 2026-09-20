# ADR-005: Provider abstraction

**Status:** Accepted (implemented)

## Context

DataHek's goal is a universal data engine, not a ClickHouse-specific tool. The archived v1
implementation generated database SQL directly, which coupled the agent to one dialect and left no
validation boundary between the model and the database.

## Decision

Every data source is a **provider** implementing the `DataProvider` contract
(`src/datahek/contracts/providers.py`):

- `provider_id`, `capabilities` (`ConnectorCapabilities`: kind, dialect, read-only level,
  `max_result_rows`, allowed aggregates),
- `connect`, `ping`, `introspect`, `compile_and_execute(client, plan, ctx)`, `close`.

Providers are created through the `ProviderRegistry` and registered in the DI container. OSS ships
ClickHouse, PostgreSQL, MySQL, SQLite, and DuckDB providers; the engine itself is dialect-free.

## Why this decision

- The model never emits provider SQL: it emits a logical plan (ADR-006) which the provider compiles.
- Capabilities let the engine enforce limits (result rows, allowed aggregates) without `if
  dialect == ...` branches.
- Adding a connector means implementing one contract — no core changes (open/closed).

## Alternatives considered

1. Direct SQL generation per database from the model (v1 approach).
2. One execution engine per database product.

## Why alternatives were rejected

- Direct SQL generation: no AST validation boundary, dialect lock-in, model errors reach the
  database, and guardrails cannot reason structurally.
- Engine-per-database: duplicated pipeline logic; guardrails and audit would need re-implementation.

## Consequences

- The guarded pipeline (validation → guardrails → execution → masking → audit) is implemented once
  in `Engine` and works for every provider.
- Provider capabilities are the single source of truth for result limits and dialect features.
- Non-SQL sources (search, files, APIs, vector stores) will implement the same contract with
  different capabilities and compilation — the engine does not assume SQL.

## Migration strategy

Existing connections keep working; the provider registry maps `Connection.provider` to the
implementation. New providers are additive.

## Revisit conditions

- A data source whose semantics genuinely cannot fit the provider contract (for example a streaming
  source) may require a contract extension — extend the contract, do not branch the engine.
