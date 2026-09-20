# ADR-009: Context Freshness

**Status:** Accepted (M2)

## Context

Different context classes decay at wildly different rates. A single TTL either serves stale schemas
or rebuilds business semantics hourly. Freshness also has correctness implications: stale
governance must never authorize, while a stale description merely degrades quality.

## Decision

Freshness is **per artifact class**, expressed as a `FreshnessReport` (state, age, whether
`schema_hash` and `permission_version` still match, next refresh due). Policies:

| Artifact | Policy |
|---|---|
| Schema | Event-driven: invalidate on `schema_hash` mismatch; no TTL |
| Profile | Periodic/age-based with row-count drift threshold |
| Taxonomy / Ontology | Version-driven: invalidate on schema or validated semantic change |
| Topology | Schema-driven: FK/index change invalidates |
| Granularity | Profile drift or human correction invalidates |
| Governance | Near-real-time: `permission_version` checked at retrieval; never served stale |
| Capabilities (skills/tools) | Registry version comparison |
| Semantics (metrics) | Long-lived until human edit |

Consumers receive freshness in the package and decide. Retrieval re-checks schema hash and
permission version on every request; rebuild is queued on mismatch while the stale package (except
governance) may be served with an explicit warning. `ContextCompiler` treats stale governance or
`QualityState.INSUFFICIENT` as fail-closed.

## Alternatives considered

1. **Global TTL for all context.** Rejected: wrong for every class simultaneously.
2. **No freshness tracking; rebuild on demand only.** Rejected: silent staleness; users learn to
   distrust answers.
3. **Block all requests on any staleness.** Rejected: availability suicide for harmless drifts.

## Trade-offs

- More policy surface and per-class logic.
- Serving stale-with-warning requires consumer discipline (enforced in the compiler, not by
  convention).

## Consequences

- `context_freshness_age_seconds` metric and freshness state per record.
- Effective staleness thresholds become tunable settings, not code constants, where feasible.

## Future Migration

Freshness policies can become configuration/entitlement-driven; the report shape stays valid.
