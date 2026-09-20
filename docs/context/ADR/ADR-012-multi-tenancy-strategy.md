# ADR-012: Multi-Tenancy Strategy

**Status:** Accepted (M2)

## Context

OSS DataHek is single-tenant by default but tenant-aware by construction (`org_id`/`project_id` on
every persistent model; `RequestContext` carries the tenant scope). The Context Layer adds
persistent artifacts and a graph; both must respect the same model without prematurely building
physical isolation.

## Decision

Application-layer tenant isolation with tenant-aware identifiers everywhere:

- Every `ContextRecord`, artifact, and graph node/edge carries `org_id` and `project_id`.
- Every context service method takes `RequestContext` and filters by tenant; no service offers a
  tenant-less access path.
- Graph queries always include the tenant scope; stable node keys incorporate tenant ids to prevent
  collisions.
- OSS runs `SingleTenantContext` (implicit `default` org/project). Enterprise can swap tenant
  resolution and, later, choose physical isolation.
- **No reliance on the graph database for isolation** — graph filters are defense in depth, not
  the authorization mechanism.

## Alternatives considered

1. **Database-per-tenant Neo4j.** Rejected for V1: operational weight; Enterprise-scope concern.
2. **Graph-only isolation (labels/properties without app filtering).** Rejected: one query mistake
   leaks cross-tenant metadata.
3. **No tenant fields until Enterprise arrives.** Rejected: the exact migration pain the platform
   baseline warns about.

## Trade-offs

- Slightly more filtering code everywhere; tests must cover cross-tenant negatives.
- Physical isolation remains a future Enterprise capability, not solved here.

## Consequences

- Context retrieval, validation, invalidation, and graph traversal are all tenant-scoped.
- Security tests include cross-tenant retrieval attempts and graph query isolation.
- Enterprise can replace `TenantContext`/registry scope rules through DI without touching domain
  logic.

## Future Migration

Schema-per-tenant or instance-per-tenant isolation can be introduced for high-compliance
Enterprise deployments; identifiers and contracts already support it.
