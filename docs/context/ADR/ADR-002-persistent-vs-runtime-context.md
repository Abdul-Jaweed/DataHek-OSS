# ADR-002: Persistent vs Runtime Context

**Status:** Accepted (M2)

## Context

Context has two very different lifetimes. Schema semantics change rarely and are expensive to
build; a user's question and its relevant slice change every request. Treating both identically
either persists throwaway data or rebuilds durable knowledge per request.

## Decision

Split context into two classes with different storage, freshness, and privacy rules:

- **Persistent Context** — schema, profile, taxonomy, ontology, topology, granularity, governance,
  validated semantics, and the Schema KG. Built by asynchronous jobs, versioned, stored durably,
  invalidated by change detection.
- **Runtime Context** — question, intent, selected tables/columns/metrics/joins, conversation
  window, applicable policy decisions, task/purpose. Assembled per request from persistent context
  plus live state; **not persisted by default**.

The compiler merges both into a `ContextPackage` scoped to one agent call and purpose.

## Alternatives considered

1. **Persist every runtime context.** Rejected: privacy risk, storage growth, no consumer.
2. **Rebuild persistent context per request.** Rejected: latency, cost, no human validation gate.
3. **Cache runtime contexts as a pseudo-persistent layer.** Rejected: invalidation complexity for
   no proven benefit in V1.

## Trade-offs

- Two code paths (build vs request) and two failure domains.
- Runtime context correctness depends on retrieval quality; persistent context quality is
  measurable and improvable out of band.

## Consequences

- Runtime context is reconstructible; persistent artifacts are durable and auditable.
- Freshness policies apply per artifact class (see ADR-009).
- Privacy rules differ: runtime may include question text transiently; persistent artifacts are
  scanned for sensitive content at build time.

## Future Migration

If debugging or evaluation later requires persisting runtime packages, they can be written as
immutable diagnostic records behind the same contract without changing the model — but only by
explicit opt-in.
