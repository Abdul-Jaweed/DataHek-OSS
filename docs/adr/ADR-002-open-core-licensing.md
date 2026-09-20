# ADR-002: Open-core licensing model

**Status:** Accepted for the OSS edition; Enterprise commercial terms pending legal review

## Context

DataHek needs a licensing model that keeps the OSS edition genuinely useful and self-hostable while
protecting the commercial Enterprise edition. Three models were evaluated in the foundation review:
open-core, source-available core plus commercial license, and fully open source plus paid service.

## Decision

Adopt **open-core**:

- This repository (`datahek-oss`) is licensed **Apache-2.0** (see `LICENSE`).
- The Enterprise edition lives in a separate, proprietary repository and is distributed
  commercially.
- Basic safety, connectors, agent runtime, API/CLI/MCP, and deployment stay in OSS. Enterprise adds
  identity, multi-tenancy, governance, centralized audit, operations, and support.

## Why this decision

- Apache-2.0 is a well-understood permissive license that maximizes community adoption.
- The Enterprise value proposition is scale, governance, and support — not artificial crippling of
  the OSS edition (baseline Risk 6).
- Commercial restriction is achieved by copyright boundary (separate repository), not by license
  traps that would deter contributors.

## Alternatives considered

1. **Source-available core** (visible source, usage restrictions) plus commercial license.
2. **Fully open source** with paid cloud/support as the only revenue.

## Why alternatives were rejected

- Source-available: protects commercialization but is significantly less attractive to the OSS
  community and complicates contribution.
- Fully open source + hosted service: the hosted-business model is not the current plan; advanced
  Enterprise modules remain commercial by design.

## Consequences

- The exact commercial license text and subscription terms require legal review before Enterprise
  distribution.
- Every contribution to this repository is Apache-2.0; contributors must not paste Enterprise code
  here.
- The open-core boundary itself (which capabilities are OSS vs commercial) is governed by ADR-014.

## Migration strategy

If the licensing model changes, the change applies through this ADR plus a LICENSE update; existing
releases remain under their original license.

## Revisit conditions

- Legal counsel advises against Apache-2.0 for competitive or patent reasons.
- A hosted DataHek Cloud offering changes the commercial calculus.
