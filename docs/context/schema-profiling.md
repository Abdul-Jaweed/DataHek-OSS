# Context Layer — Schema Profiling

**Status:** Milestone 4 deliverable
**Related:** FR-003 · ADR-009 (freshness) · ADR-013 (LLM vs deterministic)

---

## Method

Profiling is **deterministic and runs through the guarded engine**. For each selected table the
profiler builds **one aggregate `LogicalPlan`** (a `ReadNode` with many `Aggregate`s, `limit=1`)
and executes it via `Engine.execute` — so plan validation, policy evaluation, rate limits, audit,
result capping, and physical read-only enforcement all apply exactly as for user queries. The
profiler never assembles SQL itself and never calls a provider directly.

One query per table keeps cost bounded: all statistics are computed in a single pass by the
database.

## Aggregates collected

| Aggregate | Purpose |
|---|---|
| `count(*) as n` | table row count for the profile |
| `count(col) as nn_{i}` | non-null count per column |
| `count_distinct(col) as dc_{i}` | distinct count per column (optional: `include_distinct`) |
| `min(col) as mn_{i}` / `max(col) as mx_{i}` | numeric and temporal columns, non-sensitive only |
| `avg(col) as av_{i}` | numeric columns, non-sensitive only |

Derived in Python (never in SQL):

```
null_ratio        = 1 - non_null / total         (0.0 when total = 0)
uniqueness_ratio  = distinct / non_null          (None when non_null = 0)
```

Aliases are index-based (`nn_0`, `dc_0`, …) so arbitrary column names (spaces, punctuation) never
reach SQL identifiers except as quoted column references in aggregates.

## Role candidates

Candidates are proposals with confidence, never facts:

| Role | Rule | Confidence |
|---|---|---|
| `identifier` | `uniqueness_ratio ≥ 0.99` and `null_ratio == 0` | uniqueness (≤ 1.0) |
| `flag` | boolean family, or exactly 2 distinct values | 0.9 |
| `measure` | numeric family, not an identifier, not a flag | 0.9 |
| `temporal` | date/timestamp family | 1.0 |
| `dimension` | string family, ≤ 100 distinct values, not an identifier | 0.8 |

Rules are evaluated in that order; `measure` is skipped when `identifier` matched.

## Sensitive-column policy

A column is marked `sensitive` when its **name** matches a hint set (`password`, `passwd`,
`secret`, `token`, `api_key`, `apikey`, `ssn`, `social_security`, `credit_card`, `card_number`,
`cvv`, `iban`, `email`, `phone`). Unknown sensitivity is treated as sensitive (fail closed).

For sensitive columns the profiler collects **counts only** (`n`, non-null, distinct) and emits
`min_value=None`, `max_value=None`, `avg_value=None`, `role_candidates=()`. Raw text values are
never read, aggregated into extrema, or persisted.

## Zero-row and edge behavior

- `total = 0` ⇒ `null_ratio = 0.0`, `uniqueness_ratio = None`, no role candidates that require
  counts.
- A column whose aggregate is `NULL` (all null) behaves the same as zero-row for that column.
- Tables excluded by the `tables` filter simply do not appear in the artifact.

## Deferred (documented, tracked)

- **Text length ranges** (`min_length`/`max_length`) and **top-k value buckets** — the plan model
  cannot express length or grouped-per-column projections; they land when the plan model gains
  expression support. The `ColumnProfile` contract already carries the fields so consumers do not
  need to change.
- **Sampling** — not needed at current scale; `ProfileContext.sampled` remains `False`.

## Freshness and approval interactions

- Profile freshness is age/drift based (ADR-009): a row-count drift beyond the configured
  threshold marks the artifact stale without touching schema validity.
- If a table name matches the approval policy patterns, `Engine.execute` raises
  `APPROVAL_REQUIRED`; the profiler propagates it. The M8 build job records the pending approval
  instead of bypassing policy — profiling is subject to the same human gate as user queries.

## Test coverage

`tests/test_context_profiler.py` (8 tests): full column profile, measure min/max/avg, dimension and
temporal roles, sensitive-column counts-only, artifact envelope, table filtering, and zero-row
behavior — all against a scripted provider through the real `Engine`.

## Value hints (low-cardinality examples)

For **non-sensitive string columns** whose distinct count is at or below
`DATAHEK_PROFILE_HINT_MAX_DISTINCT` (default 25), the profiler also records the top
`DATAHEK_PROFILE_HINT_TOP_K` (default 5) values as `ColumnProfile.top_values`. These hints are
rendered into the planner's schema block (`service_name:text (e.g. ad, checkout, payment)`) so the
model can match entities and encoded categories without guessing.

Privacy guards: sensitive-patterned columns are skipped, free-text/identifier columns
(`*_id`, `*_message`, `*_url`, JSON, …) are skipped, values are truncated to 24 characters, and at
most `DATAHEK_PROFILE_HINT_MAX_COLUMNS` (default 6) columns per table are hinted. Disable
entirely with `DATAHEK_PROFILE_VALUE_HINTS=off`.

Cost: each hint is a grouped `count(*)` scan of the table through the guarded engine. On the
InsForge fixture (730k rows) six hints add ~17 s to the build (PROFILE ≈ 27 s → 44 s), which is a
one-time build cost. Exact counts are kept; sampling/approximate distinct for very large tables
remains future work.
