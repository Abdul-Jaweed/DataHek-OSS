# ADR-010: Schema Change Detection

**Status:** Accepted (M2)

## Context

A schema change invalidates most context. Detecting change must be cheap, deterministic, and
precise enough to avoid gratuitous rebuilds. Options range from full re-introspection comparison
to database triggers/CDC (not feasible: DataHek owns no triggers in user databases).

## Decision

Use **canonical schema hashing** plus lightweight drift checks:

- Canonicalize the schema snapshot (sorted tables/columns, normalized types, PK/FK/index
  structure, nullability; comments excluded from the hash because they are untrusted text).
- Compute `schema_hash = SHA-256(canonical_form)` at build time; persist on the context record and
  on every graph node/edge.
- Detection points: (a) connection test / introspection on demand, (b) retrieval-time check when a
  cached introspection is available (TTL from the existing `SchemaService` cache), (c) scheduled
  rebuild checks in deployments that enable them.
- On mismatch: mark records `STALE`, audit `schema_changed`, queue rebuild, and let the compiler
  serve stale-with-warning until the rebuild publishes.
- Row-count drift beyond a threshold marks Profile `STALE` without affecting schema validity.

## Alternatives considered

1. **Database triggers / CDC.** Rejected: intrusive, provider-specific, and not available for all
   connectors.
2. **Full re-introspection on every request.** Rejected: latency and load for a rare event.
3. **Timestamp-based change detection only.** Rejected: unreliable across engines.

## Trade-offs

- Comments excluded from the hash: comment-only changes do not trigger rebuilds (acceptable; they
  are untrusted and low-value).
- Detection is poll-on-use, not instant; worst case is one stale-served request with warning.

## Consequences

- Rebuilds are deterministic and idempotent; `schema_hash` is a first-class field across registry,
  store, and graph.
- Topology/granularity invalidate through the same mechanism.

## Future Migration

If connectors gain change streams later, they feed the same invalidation path; hashing remains the
source of truth.
