# Context Layer — Schema Knowledge Graph

**Status:** Milestone 7 deliverable
**Related:** FR-009, FR-017 · ADR-003 (schema KG) · ADR-005 (abstraction) · ADR-011 (projection)
> **Full design & implementation guide:** [`schema-knowledge-graph.md`](schema-knowledge-graph.md)

The Schema KG is a **projection** of context artifacts — schema, profiles, topology, granularity,
taxonomy, metrics, and ontology — into a `GraphRepository`. It stores metadata and semantics,
never row data, and can be rebuilt from the registry/store at any time.

## Node labels and ids

| Label | Id scheme | Key properties |
|---|---|---|
| `Connection` | `connection:<connection_id>` | `name` |
| `Table` | `table:<connection_id>:<table>` | `name`, `row_count`, `grain`, `grain_confidence` |
| `Column` | `column:<connection_id>:<table>.<column>` | `name`, `data_type`, `nullable`, `is_primary_key`, `is_foreign_key`, `references`, `null_ratio`, `distinct_count`, `uniqueness_ratio`, `roles`, `sensitive`, `taxonomy_category` |
| `Metric` | `metric:<connection_id>:<name>` | `name`, `table`, `aggregate`, `column`, `filter`, `description` |
| `Concept` | `concept:<connection_id>:<name>` | `name`, `kind`, `description`, `synonyms`, `validation` |

Every node also carries `connection_id`, `org_id`, `project_id`, `context_version`, `schema_hash`,
`provenance`, `created_at`, and `updated_at`. Labels never come from user text; relationship
targets are created only when both endpoints exist in the projection.

## Edge vocabulary (ADR-003 only)

| Edge | From → To | Source |
|---|---|---|
| `HAS_TABLE` | Connection → Table | schema |
| `HAS_COLUMN` | Table → Column | schema |
| `REFERENCES` | Column → Column | topology FK edges (confidence 1.0) |
| `JOINS_WITH` | Column → Column | inferred topology edges (confidence, `kind`, `cardinality`, `fanout_risk` properties) |
| `HAS_METRIC` | Table → Metric | semantic layer |
| `DESCRIBES` | Concept → Table | ontology `maps_to` |
| `SEMANTICALLY_RELATED_TO` | Concept → Concept | ontology relationships (`kind`/`predicate` properties) |

Relationship ids are deterministic: `rel:<TYPE>:<source>-><target>`, with concept-to-concept edges
disambiguated by ontology kind. Re-running a build therefore MERGEs existing edges instead of
duplicating them.

## Idempotency and pruning

- `SchemaGraphBuilder.build(...)` writes nodes first (endpoints before edges), then relationships.
- Stable ids + upsert semantics make rebuilds idempotent: a second identical build reports
  `nodes_pruned=0` and the same counts.
- After writing, the builder prunes per label: any node stamped with this `connection_id` that is
  not in the desired set is deleted (its relationships go with it). A removed table or column
  disappears from the graph on the next build.

## Degraded behavior

If the repository is absent or `health_check()` is false, `build` returns
`GraphBuildReport(degraded=True, warnings=("graph backend unavailable",))` with zero counts. The
build itself never raises for graph unavailability — the registry/store remain the source of truth
(FR-009, failure modes).

## Reading the graph

```cypher
// tables and their columns, tenant-scoped, active version
MATCH (t:DataHekNode {label: 'Table'})-[:HAS_COLUMN]->(c:DataHekNode)
WHERE t.org_id = 'default' AND t.connection_id = 'insforge-live'
RETURN t.p_name, c.p_name, c.p_roles;

// join candidates around a column
MATCH (c:DataHekNode {id: 'column:insforge-live:orders.customer_id'})
      -[:REFERENCES|JOINS_WITH]-(target)
RETURN target.id;
```

(Property names are prefixed `p_` in the store; adapters translate to plain names.)

## Verification

Live projection of the InsForge `unified_events` + `ecommerce_sales` artifacts: 48 nodes
(1 connection + 2 tables + 45 columns), 47 relationships, idempotent rebuild, ~30 ms reads.
Tests: `tests/test_context_graph_builder.py` (7) plus the shared graph contract suite (13).
