# ADR-004: Neo4j as the Initial Graph Implementation

**Status:** Accepted (M2)

## Context

The Schema KG needs a graph engine. Candidates: Neo4j (property graph, Cypher, mature), FalkorDB
(Redis-protocol OpenCypher subset, SSPLv1), PostgreSQL extensions/CTEs (already deployed). The
project is Apache-2.0 OSS with a commercial Enterprise edition; licensing and operational cost
matter, and the graph must remain replaceable.

## Decision

**Neo4j Community Edition is the initial graph backend**, consumed as a separate service over Bolt
via the official Python driver (Apache-2.0). Facts behind the choice:

- Neo4j Community is **GPLv3**; it runs as an independent server process, so it does not extend to
  DataHek's Apache-2.0 code. The driver is Apache-2.0.
- Cypher and tooling (`EXPLAIN`, constraints, indexes) are mature and inspectable.
- FalkorDB is **SSPLv1**: using it as part of a service offered to others triggers open-sourcing
  obligations for the service — risky for the DataHek product posture. It remains a possible
  adapter for internal-only deployments.
- PostgreSQL remains the license-safe fallback (ADR-011).

Deployment: Neo4j is an **optional compose profile** (`--profile graph`), not part of the default
OSS stack. The core package installs without the driver (`[graph]` extra); context features
degrade cleanly when absent.

## Alternatives considered

1. **FalkorDB first.** Rejected: SSPLv1 service trigger conflicts with offering DataHek as a
   hosted service; OpenCypher subset adds compatibility gaps.
2. **PostgreSQL graph first.** Rejected as the primary: recursive-CTE ergonomics for multi-hop
   semantic queries are poor; AGE adds an extension to the stack. Kept as fallback adapter.
3. **Embedded/bundled graph engine.** Rejected: additional runtime coupling; none is a natural fit.

## Trade-offs

- Neo4j is a JVM service with memory tuning; operators pay a real cost when enabling the feature.
- GPLv3 must be documented for users running the graph profile.

## Consequences

- `Neo4jGraphRepository` is one adapter behind `GraphRepository` (ADR-005).
- Compose gains an optional `neo4j` service; default stack unchanged.
- License obligations: DataHek does not redistribute Neo4j binaries; it documents the optional
  dependency and license.

## Future Migration

FalkorDB and PostgreSQL adapters implement the same contract and pass the same contract tests
(ADR-005). The domain never imports Neo4j types, so migration is adapter + wiring work.
