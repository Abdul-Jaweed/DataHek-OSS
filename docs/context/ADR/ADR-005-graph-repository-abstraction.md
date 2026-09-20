# ADR-005: Graph Repository Abstraction

**Status:** Accepted (M2)

## Context

The brief makes graph replaceability a hard architectural requirement: "Neo4j can be replaced
without rewriting the Context Domain." Graph engines differ in query language, protocol, and
transaction semantics; leaking any of that into the domain would create exactly the vendor lock-in
the requirement forbids.

## Decision

Define an engine-independent `GraphRepository` protocol in `contracts/context.py`:

```python
async def create_node(ctx, node: GraphNode) -> str
async def update_node(ctx, node: GraphNode) -> None
async def delete_node(ctx, node_id: str) -> None
async def get_node(ctx, node_id: str) -> GraphNode | None
async def find_nodes(ctx, *, label, where=None, limit=100) -> list[GraphNode]
async def create_relationship(ctx, rel: GraphRelationship) -> str
async def delete_relationship(ctx, rel_id: str) -> None
async def neighbors(ctx, node_id, *, rel_type=None, depth=1) -> list[GraphNode]
async def paths(ctx, *, from_id, to_id, max_depth=3, rel_types=None) -> list[GraphPath]
async def health_check() -> bool
```

Domain models `GraphNode`, `GraphRelationship`, `GraphPath` are plain dataclasses with typed
`properties` maps — **no Cypher, no Bolt, no Neo4j types**. `context/graph/neo4j.py` is the only
module allowed to know Cypher; it builds queries from typed inputs (no string interpolation of
untrusted text).

Every backend must pass one shared **contract test suite** (create/read/update/delete node,
create/delete relationship, traversal, paths, tenant isolation, version filtering, provenance
round-trip, idempotency via stable keys, health check).

## Alternatives considered

1. **Use the Neo4j driver directly in domain services.** Rejected: violates the replaceability
   requirement, embeds Cypher everywhere.
2. **Define the domain model in Cypher terms (labels/queries as data).** Rejected: vendor lock-in
   by another name.
3. **No abstraction — swap later if needed.** Rejected: the brief names replaceability a hard
   requirement, and retrofitting is the expensive path.

## Trade-offs

- The protocol cannot expose every vendor feature; advanced specifics stay adapter-only.
- Some queries may be less efficient than hand-tuned Cypher; acceptable for metadata-scale graphs.
- Contract tests add CI surface for every backend.

## Consequences

- Neo4j, FalkorDB, and PostgreSQL adapters are interchangeable at wiring time.
- An in-memory fake adapter passes the same suite, enabling domain tests without Neo4j.
- Graph query latency and behavior are normalized behind one interface for observability.

## Future Migration

New backends implement the protocol and join the contract suite. If a backend needs a capability
the protocol lacks, extend the protocol (additive) with an ADR — never bypass it from domain code.
