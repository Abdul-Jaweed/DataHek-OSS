# Context Layer — Granularity

**Status:** Milestone 5 deliverable
**Related:** FR-008 · research.md §6

Grain is a **correctness input**, not documentation. `SUM(amount)` over an item-grain table
double-counts an order; the Context Layer therefore states grain explicitly and marks how much it
can be trusted.

## Table grain

`build_granularity_context(schema, profiles=None, *, metrics=()) -> GranularityContext`

| Structural fact | Statement | Confidence |
|---|---|---|
| Single-column primary key, profiled as `identifier` | `1 row of orders = 1 Order` | 0.9 |
| Single-column primary key, unprofiled | same statement | 0.7 |
| Single-column primary key, profiled but not unique | same statement | 0.6 |
| Composite primary key | `1 row of order_items = 1 OrderItem identified by (order_id, sku)` | 0.8 |
| No primary key | `1 row of events = 1 Event (unconfirmed)` + qualifier `no primary key; grain unverified` | 0.3 |

Entity names come from naive singularization (`orders → Order`, `categories → Category`,
`business → Business`), sufficient for statements that humans validate anyway.

All statements carry `source=SYSTEM`, `validation=PENDING` — the canonical acceptance scenario is
a human confirming "one row represents one order" (ADR-008).

## Metric grain

Given metric definitions (`name`, `table`), each metric maps to its table's grain:

- Table present → `valid_at=(statement,)`; a caveat is added when the grain is unverified
  (`confidence < 0.5`): *"grain unverified; aggregation may be incorrect"*.
- Table absent from context → `valid_at=("unknown",)` with *"table 'x' not in context"*.

Deferred: multi-table metric paths, cross-grain joins (metric valid at order grain but queried via
items), and time-grain statements (`daily` vs `monthly`) — these need join-path awareness and land
with retrieval/composition.

## Tests

`tests/test_context_granularity.py` (6): singularization forms, identifier-confirmed single PK,
composite PK qualification, unverified no-PK marker, metric grain mapping, caveat for unverified
tables.
