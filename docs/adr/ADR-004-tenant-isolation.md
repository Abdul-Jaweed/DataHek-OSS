# ADR-004: Tenant isolation strategy

**Status:** Accepted (OSS single-tenant, tenant-aware models)

## Context

Multi-tenancy is an Enterprise capability, but the foundation review identified late tenancy as a
top foundation risk: retrofitting tenancy after conversations, connections, audit, and MCP exist
requires changing every function signature and every table.

## Decision

- OSS runs **single-tenant by default** (`SingleTenantContext` resolves an implicit default
  organization/project).
- Every persistent model and every request is **tenant-aware from the start**:
  - `RequestContext` carries `organization_id`, `workspace_id`, `project_id`, `user_id`, `roles`,
    `permissions`, `authenticated`, `source`, and `request_id`.
  - Persistent records carry `org_id` / `project_id` columns.
- Enterprise will add the full organization model and PostgreSQL row-level security, with
  application-level authorization as the primary gate and RLS as defense in depth.

## Why this decision

- OSS users never pay multi-tenant complexity; Enterprise can adopt tenancy without touching every
  call site.
- A normalized request context is the single place where identity and tenancy meet, for every
  surface (API, CLI, MCP, scheduler).

## Alternatives considered

1. Multi-tenant OSS from day one (organizations, memberships, workspaces in the core).
2. No tenancy fields until Enterprise exists.

## Why alternatives were rejected

- Multi-tenant OSS: complexity with no user for it; violates "OSS must be simple to self-host".
- No tenancy fields: exactly the migration pain the foundation review flagged (Risk 3).

## Consequences

- Context construction helpers (`_request_context` in the API, `_mcp_context` in MCP, CLI context
  construction) must populate identity fields rather than defaults. This is implemented; policy and
  RBAC consumption of `roles`/`permissions` remains an Enterprise concern.
- `user_id` alone is never the authorization model; org/project always accompany it.

## Migration strategy

Single-tenant deployments map to one implicit organization/project (`default`). Enterprise
onboarding assigns real organization and project identifiers; existing rows migrate by backfilling
the default identifiers.

## Revisit conditions

- Enterprise tenant isolation strategy (shared PG + RLS vs schema-per-tenant vs database-per-tenant)
  is finalized — this ADR will be extended, not replaced.
