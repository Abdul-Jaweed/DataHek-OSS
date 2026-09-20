# Context Layer — Taxonomy

**Status:** Milestone 5 deliverable
**Related:** FR-005 · ADR-008 · research.md §4

Taxonomy answers **"what kind of thing is this?"** — a browsable classification of columns derived
from profile roles. It is kept strictly separate from ontology (meaning and relationships).

## Structure

```
<Domain>                      (parameter; default "General")
└── <table>                   node_kind="subdomain", members=(table,)
    ├── Identifier            members=("orders.order_id", ...)
    ├── Measure               members=("orders.amount", ...)
    ├── Dimension             members=("orders.status", ...)
    ├── Temporal              members=("orders.created_at", ...)
    └── Flag                  members=("orders.is_error", ...)
```

Category assignment uses the **first matching role** in profile order
(`identifier → flag → measure → temporal → dimension`), so an identifier that is also numeric is
classified once, as an Identifier.

## Rules

- Source of truth: `ProfileContext.role_candidates` (M4) — deterministic rules over statistics.
- **Sensitive columns are excluded entirely** (`sensitive=True` columns never appear in taxonomy
  members, even in category nodes).
- Columns without roles are omitted (no invented categories).
- Node provenance `SYSTEM`, validation `PENDING`, confidence = mean role confidence for the table
  (0.8 fallback) — humans confirm the taxonomy in M9.

## Deferred

- Multi-domain taxonomies and cross-table entities (`order_items` as an entity inside `orders`) —
  ontology's job; taxonomy stays column-oriented.
- LLM-suggested business categories — the enricher focuses on ontology first (ADR-013).

## Tests

`tests/test_context_taxonomy.py` (3): hierarchy construction, sensitive/untyped exclusion,
provenance and validation status.
