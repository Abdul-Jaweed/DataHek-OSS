# ADR-011: PostgreSQL vs Neo4j Storage Responsibilities

**Status:** Accepted (M2)

## Context

The Context Layer has three storage concerns: lifecycle metadata, artifact payloads, and semantic
relationships. Forcing all three into Neo4j would couple core functionality to an optional graph
backend; keeping all three in PostgreSQL would make graph traversal awkward.

## Decision

Separate responsibilities:

| Concern | Store | Rationale |
|---|---|---|
| **Context Registry** (records, lifecycle, versions, hashes, quality/freshness summaries) | **PostgreSQL** (SQLite default) | Transactional metadata; must survive graph outages; already part of the OSS stack with versioned migrations |
| **Context Store** (artifact payloads, immutable versions) | **PostgreSQL** (SQLite default) | Durable, queryable by key; payloads are structured documents, not relationships |
| **Schema Knowledge Graph** (semantic relationships, traversal, paths) | **Neo4j** (optional) | Purpose-built for multi-hop semantic queries |
| **Derived caches** (retrieval results, compiled packages) | In-process, versioned keys | Rebuildable; must never be authoritative |

The graph is a **projection**: it can be rebuilt from registry + store at any time. Writes follow
registry → store → graph; graph failures mark `DEGRADED`, never block state transitions.

## Alternatives considered

1. **Everything in Neo4j.** Rejected: couples core to an optional service; Neo4j is not a
   transactional metadata store for this use case.
2. **Everything in PostgreSQL.** Rejected: recursive CTEs make bounded multi-hop semantic queries
   painful and slow; AGE adds an extension dependency.
3. **Put registry in the graph for "one store."** Rejected: violates availability posture.

## Trade-offs

- Two write paths and a reconciliation concern (registry vs graph counts).
- Operators wanting graph features must run Neo4j; documented as optional compose profile.

## Consequences

- `ContextStore` and `ContextRegistry` contracts are backend-agnostic; SQLite and PostgreSQL
  implementations ship in `defaults/`.
- Graph rebuild tooling is a supported operation from day one.
- Reconciliation metric compares registry and graph state.

## Future Migration

A PostgreSQL graph adapter would collapse stores 2+3 for minimal deployments without domain
changes; a FalkorDB adapter swaps store 3. The registry remains PostgreSQL/SQLite regardless.
