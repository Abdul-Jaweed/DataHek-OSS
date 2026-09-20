# ADR-006: Context Registry

**Status:** Accepted (M2)

## Context

Context artifacts are versioned, lifecycle-managed, and provenance-tracked. Consumers need to
answer: which context is ACTIVE for this tenant/connection/table, which version, is it stale, what
changed, and what is safe to serve. Without a registry, lifecycle state would be inferred from
storage contents — unverifiable.

## Decision

Introduce a **Context Registry** as the authority for context metadata:

- `ContextRecord` per `(org, project, connection, scope, version)` with `state`, `schema_hash`,
  `quality`, `freshness`, artifact kinds, provenance summary, timestamps, and `supersedes` links.
- Operations: register, get, find by tenant/connection/table, `set_state`, `invalidate` (bulk by
  connection), `versions`, and "active record" lookup.
- The registry stores **metadata**; payloads live in the Context Store (ADR-011). Registry state is
  durable and migrated like other platform metadata (PgMetadata migrations; SQLite default).
- Lifecycle transitions are validated in `context/lifecycle.py` (legal transitions only; illegal
  transitions raise). Registry writes are audited.

## Alternatives considered

1. **Infer state from store contents** (e.g., newest artifact row). Rejected: no explicit STALE/
   DEGRADED/FAILED semantics; races between concurrent builds.
2. **Store registry in the graph.** Rejected: registry must survive graph outages (ADR-011).
3. **No versioning — overwrite artifacts.** Rejected: breaks auditability, human validation
   history, and safe rollback.

## Trade-offs

- Two-phase writes (registry + store) need care; V1 uses ordered writes with idempotent repair
  (registry first, then payload, then state → ACTIVE).
- Extra table surface to migrate.

## Consequences

- Retrieval starts at the registry (cheap lookup) and then loads payloads — no store scans.
- Invalidation, rebuild, and freshness checks all anchor on registry state.
- Graph projection can always be rebuilt from registry + store (registry is source of truth).

## Future Migration

If a centralized metadata store arrives with Enterprise, the registry contract is already the
seam; background reconciliation tools can compare registry against store/graph for drift.
