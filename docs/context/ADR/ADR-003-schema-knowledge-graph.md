# ADR-003: Schema Knowledge Graph

**Status:** Accepted (M2)

## Context

The brief distinguishes a data knowledge graph (nodes for rows/entities, edges for record-level
relationships) from a schema knowledge graph (nodes for tables/columns/concepts, edges for
structure and meaning). DataHek is a read-only query engine with strict privacy rules; a data-level
graph would require ingesting and duplicating user data.

## Decision

DataHek builds a **Schema Knowledge Graph**: nodes for `Tenant`, `Connection`, `Database`,
`Schema`, `Table`, `Column`, `Metric`, `Dimension`, `Entity`, `Concept`, `DataType`, `Constraint`,
`Skill`, `Tool`, `ProfileSnapshot`; a controlled relationship vocabulary (`OWNS`, `HAS_SCHEMA`,
`HAS_TABLE`, `HAS_COLUMN`, `HAS_METRIC`, `HAS_DIMENSION`, `REFERENCES`, `JOINS_WITH`,
`INSTANCE_OF`, `BELONGS_TO`, `SEMANTICALLY_RELATED_TO`, `MEASURES`, `IDENTIFIES`, `OCCURS_AT`,
`DESCRIBES`, `VALIDATED_BY`). New node/relationship types require an ADR update.

Every node/edge carries `org_id`, `context_version`, `schema_hash`, and provenance. The graph
stores metadata and semantics — never row data or raw values.

## Alternatives considered

1. **Data knowledge graph.** Rejected for V1: privacy, cost, freshness, and scope (§48 non-goals).
2. **No graph — relational tables only.** Rejected: relational joins express schema structure fine
   but make multi-hop semantic questions ("concepts related to revenue") awkward and slow.
3. **Free-form property bag graph.** Rejected: uncontrolled vocabularies create unqueryable,
   inconsistent graphs.

## Trade-offs

- A controlled vocabulary requires governance and limits expressiveness.
- Graph freshness adds a synchronization concern (registry is source of truth; graph rebuildable).

## Consequences

- The graph is a **projection** of registry/store state, rebuildable at any time.
- Semantic questions (related concepts, join paths) become graph traversals rather than scans.
- Graph absence never corrupts canonical state (see ADR-005, ADR-011).

## Future Migration

V2+ may add data-level or cross-database graphs as separate, opt-in projections; the schema KG is
the foundation they would extend, not replace.
