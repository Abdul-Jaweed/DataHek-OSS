# Context Layer — Multi-Tenancy

**Status:** Milestone 12 deliverable
**Related:** FR-018 · ADR-012 · [security.md](security.md) · [context-model.md](context-model.md)

Multi-tenancy is a **data-model concern of the OSS core**, even though tenant *management* is an
Enterprise capability. The OSS edition runs single-tenant (`SingleTenantContext` resolves
`default/default`), but every persistent object already carries its ownership boundary so nothing
has to be migrated later.

## Ownership model

```
organization_id
  └── project_id
       └── connection_id
            └── context_id (scope: connection)
                 ├── artifacts (schema, profile, topology, granularity, taxonomy, ontology,
                 │              governance, capability, quality, freshness)
                 └── versions (immutable, superseded)
```

`ContextRecord` stores `org_id`/`project_id`; `ContextPackage` carries them plus `connection_id`.
Graph nodes/edges carry `org_id` and `connection_id` properties (ADR-005/007).

## Enforcement points

| Layer | Rule |
|---|---|
| `ContextRegistry` / `ContextStore` | Every read/write filters `org_id`; cross-tenant writes raise `NOT_FOUND` |
| `ContextRegistryService` | `active`/`is_current`/`invalidate` are tenant-scoped pass-throughs |
| `ContextValidationService` | Review and publish act only on the caller's active record |
| `ContextRetrieverService` | Reads through the scoped registry; a foreign record simply doesn't exist |
| Graph adapters | `org_id` on every node/edge and every read (ADR-005) |
| API | `RequestContext(source="api")` (identity-aware when auth is on) feeds all context endpoints |

When authentication is enabled, `_request_context` populates `user_id`/`roles`/`permissions` and
the tenant resolver supplies `organization_id`; with auth off, the single-tenant default applies.
Cross-tenant tests: `tests/test_context_security.py::TestTenantIsolation`.

## Versioning per tenant

Versions are monotonic **per `(org_id, connection_id, scope)`**. Two tenants building the same
connection name never collide — ids include the tenant, and `supersedes` chains stay within the
tenant.

## Enterprise extensions (ADR-012 boundary)

Tenant/workspace/team management, per-connection RBAC, row-level policies, quotas, and
tenant-aware audit are Enterprise concerns layered on these same interfaces. The OSS core
guarantees only the isolation invariant; it does not manage tenants.
