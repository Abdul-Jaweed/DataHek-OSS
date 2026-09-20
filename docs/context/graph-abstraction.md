# Context Layer — Graph Abstraction

**Status:** Milestone 6 deliverable
**Related:** FR-009, FR-017 · ADR-005 · ADR-012

The Schema Knowledge Graph (M7) is built through a **replaceable** contract. Replacing Neo4j must
never require touching the context domain — that is a hard architectural requirement, not a
preference.

## Contract

`GraphRepository` (`contracts/context.py`) with `GraphNode`, `GraphRelationship`, `GraphPath`:

```
create_node / update_node / delete_node / get_node / find_nodes
create_relationship / delete_relationship
neighbors(node_id, rel_type?, depth)   # returns nodes, tenant-scoped
paths(from_id, to_id, max_depth, rel_types?)   # bounded, capped at 10
health_check
```

Rules every adapter must honour:

1. **Tenant-scoped reads.** `get_node`, `find_nodes`, `neighbors`, `paths` filter by
   `ctx.organization_id`; a cross-tenant lookup returns nothing (application-layer isolation,
   ADR-012).
2. **Upsert by stable id.** `create_node` on an existing id replaces it, making graph rebuilds
   idempotent; `update_node` on a missing node raises `NOT_FOUND`.
3. **Controlled relationship vocabulary.** Types are validated against
   `context/graph/vocabulary.py` (ADR-003) before anything is written; unknown types raise
   `VALIDATION`. Adding a type is an ADR change.
4. **Idempotent deletes.** Deleting a missing node/relationship is a no-op.
5. **Bounded reads.** `neighbors` depth and `paths` depth/limit are capped; adapters must not
   allow unbounded traversal.
6. **No engine leakage.** Cypher/Bolt types stay inside `context/graph/neo4j.py`; the domain sees
   only contract dataclasses.

## Contract test suite

`tests/graph_repository_contract.py` holds `GraphRepositoryContract` — 13 tests covering
create/get/update/delete, upsert idempotency, label/property filtering, tenant isolation,
relationship traversal and type filtering, depth-two traversal, bounded paths, delete cascades,
idempotent relationship deletes, vocabulary rejection, and health checks.

Adapters subclass it:

```python
# tests/test_graph_memory.py
class TestInMemoryGraph(contract.GraphRepositoryContract):
    def make_repo(self): return InMemoryGraphRepository()
```

The suite runs one event loop per test (`loop.run_until_complete`) because async graph drivers are
loop-affine; adapters with a `close()` method are closed in `tearDown`.

## Adapters

| Adapter | Module | Use |
|---|---|---|
| `InMemoryGraphRepository` | `context/graph/memory.py` | Unit tests, graph-less mode, future federation tests |
| `Neo4jGraphRepository` | `context/graph/neo4j.py` | Production Schema KG (see [neo4j.md](neo4j.md)) |
| Planned | FalkorDB / PostgreSQL | Same contract; must pass the same suite |

## Adding a backend

1. Implement the ten protocol methods; keep the engine SDK imported lazily.
2. Make `tests/test_graph_<name>.py` subclass the contract suite (gate on an env URL like
   `DATAHEK_TEST_<NAME>_URL`).
3. Run the suite against a live instance — "passes the contract" is the definition of done.
4. Add registration wiring behind env configuration (override pattern, not edition checks).
5. Do not add engine-specific types to `contracts/context.py`.
