# ADR Index

Architecture decision records for DataHek OSS. Format follows the baseline established in the
DataHek architecture review: **Context / Decision / Why this decision / Alternatives considered /
Why alternatives were rejected / Consequences / Migration strategy / Revisit conditions**.

All ADRs are tracked in `docs/adr/` (the rest of `docs/` stays local-only).

| ADR | Title | Status |
| --- | --- | --- |
| [ADR-001](ADR-001-separate-repositories.md) | Separate OSS and Enterprise repositories | Accepted |
| [ADR-002](ADR-002-open-core-licensing.md) | Open-core licensing model | Accepted (commercial terms pending legal review) |
| [ADR-003](ADR-003-postgresql-metadata.md) | PostgreSQL metadata store | Accepted (implemented) |
| [ADR-004](ADR-004-tenant-isolation.md) | Tenant isolation strategy | Accepted (OSS single-tenant, tenant-aware models) |
| [ADR-005](ADR-005-provider-abstraction.md) | Provider abstraction | Accepted (implemented) |
| [ADR-006](ADR-006-logical-query-plan.md) | Logical query plan | Accepted (implemented) |
| [ADR-007](ADR-007-guardrails-spi.md) | Guardrails SPI | Accepted (native pipeline implemented; adapters future) |
| ADR-008 | OpenTelemetry observability | Proposed (current: Prometheus text + JSON logs) |
| ADR-009 | Authentication architecture | Open (local API keys implemented; SSO is Enterprise) |
| ADR-010 | Policy engine architecture | Proposed (LocalPolicyEngine implemented; central engine is Enterprise) |
| ADR-011 | Conversation persistence | Accepted (implemented: SQLite default, PostgreSQL opt-in) |
| ADR-012 | Job queue | Open (in-process scheduler now; Redis-backed queue is Enterprise) |
| ADR-013 | Secrets management | Accepted (implemented: env + Infisical; encryption at rest opt-in) |
| ADR-014 | OSS/Enterprise packaging and entitlements | Accepted (implemented: entitlement layer, static OSS limits) |

Open questions from the baseline that still need a decision are tracked in the
[OSS/Enterprise review](https://github.com/Abdul-Jaweed/DataHek-OSS) discussion — notably:
Production-tier placement, OSS limit overridability, and Enterprise repository privacy.
