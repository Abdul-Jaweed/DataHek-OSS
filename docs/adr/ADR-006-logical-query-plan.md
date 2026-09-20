# ADR-006: Logical query plan

**Status:** Accepted (implemented)

## Context

The system input is a natural-language question; the system output must be a validated, safe,
read-only query against an arbitrary data source. The model is untrusted and fallible, and
providers have different dialects.

## Decision

The agent produces a **versioned, serializable, provider-agnostic `LogicalPlan`**
(`src/datahek/engine/plan.py`), never provider SQL:

- Plan nodes are `ReadNode`s with columns, filters, joins (max 2), group-by, aggregates, order-by,
  and a limit.
- `validate_plan` checks structure against the discovered schema before anything executes.
- Providers compile the plan to their dialect (`engine/compile.py` for SQL providers,
  `compile_and_execute` in the provider contract).

The flow is: question → planner (LLM) → logical plan → validation → guardrails → provider compile →
execute → mask → explain.

## Why this decision

- One validation boundary: guardrails and schema validation inspect a structured plan, not a
  string of SQL.
- Dialect independence: the same plan compiles to ClickHouse, PostgreSQL, MySQL, SQLite, or DuckDB.
- Replayability: plans are persisted in checkpoints and can be re-executed deterministically
  without the LLM.
- LLM mistakes become `PLAN_INVALID` errors or clarifications, never silent bad SQL.

## Alternatives considered

1. Direct SQL generation from the model (the archived v1 flow).
2. An ORM-based query builder owned by the core.

## Why alternatives were rejected

- Direct SQL: validation of arbitrary SQL strings is weaker (must re-parse anyway), and the
  planner would need per-dialect prompt engineering.
- Core-owned builder: recreates the dialect coupling the provider abstraction removes; providers
  would lose the ability to express native constructs.

## Consequences

- Plan format changes require a version bump (`LogicalPlan.version`) and checkpoint compatibility
  handling.
- Complex SQL features (window functions, CTEs) are intentionally out of scope; plans cover
  read-only analytical querying.
- `DEFAULT_LIMIT` (currently 10) applies when a plan specifies no limit; provider
  `max_result_rows` caps any larger limit.

## Migration strategy

Versioned plan dicts in checkpoints are read through the current model; unknown versions are
rejected with a clear error rather than executed.

## Revisit conditions

- Evaluation shows the plan model blocks a class of valuable questions (for example windowed
  analytics) — extend the plan model, do not bypass it.
