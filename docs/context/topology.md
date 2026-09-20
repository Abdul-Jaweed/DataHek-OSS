# Context Layer — Topology

**Status:** Milestone 5 deliverable
**Related:** FR-007 · ADR-013 · research.md §5

Topology is **structural connectivity** — how tables join — and is deliberately separate from
ontology (meaning). It answers the planner's practical question: *can I join these tables, on which
columns, and with what expected fan-out?*

## Edges

| Kind | Source | Provenance | Confidence |
|---|---|---|---|
| `fk` | Catalog foreign keys (SQLite PRAGMA, PostgreSQL information_schema) | `DATABASE` | 1.0 |
| `inferred` | Rule: `<entity>_id` column → `<entity>` table's single-column primary key, type families equal | `INFERRED` | 0.6 |

Inferred edges never duplicate FK edges, never self-join a table, and require the target to have a
single-column primary key with a compatible type family. They are **proposals** — consumers treat
confidence accordingly, and human validation can promote or reject them (M9).

Deferred (documented): same-name column inference beyond the `_id` rule, cross-schema/cross-database
topology, and cardinality estimation from profile uniqueness beyond the N:1 default.

## Cardinality and fan-out

Edges currently carry `N:1` with `fanout_risk="low"` (the referenced side is a primary key).
Profile-informed cardinality (1:1 vs N:1 from uniqueness ratios, `fanout_risk` from duplicate
keys) is a planned refinement once profiles are wired into the topology build.

## Join paths

`TopologyContext.join_paths["a->b"]` holds up to three distinct paths (each a tuple of
`left=right` edge references) with a hard depth bound (default 3, configurable). Paths are
bidirectional — both `a->b` and `b->a` are emitted — and cycles are excluded per path. Bounded
traversal is what keeps retrieval honest: the planner gets the join it needs, not the whole graph.

## Artifact

`build_topology_context(schema, *, max_depth=3) -> TopologyContext`; envelope provenance
`SYSTEM`, trust `STRUCTURAL`, validation `PENDING` (FK facts are structural; the artifact as a
whole awaits human review of its inferred edges).

## Tests

`tests/test_context_topology.py` (5): inference rule, FK deduplication, missing-target skip,
edge provenance/confidence, direct and two-hop paths, depth bounding.
