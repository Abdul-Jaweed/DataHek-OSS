# ADR-001: Separate OSS and Enterprise repositories

**Status:** Accepted
**Decision type:** Foundational

## Context

DataHek ships as two editions: a self-hostable open-source core (this repository) and a commercial
Enterprise edition. Both must share the platform kernel: contracts, provider abstraction, logical
planning, guardrails, audit, evaluation, and experience surfaces. The original foundation review
recommended a monorepo first; the follow-up review revisited that recommendation.

## Decision

DataHek uses **separate repositories**:

- `datahek-oss` (this repository) contains the complete universal data engine and all stable
  extension contracts.
- `datahek-enterprise` depends on a **versioned OSS release** and adds enterprise-only
  implementations, policies, services, and deployment options.
- Enterprise must not become a separate implementation of the platform: it imports and extends OSS
  packages, never copies them.

## Why this decision

- OSS carries an Apache-2.0 license and public history; Enterprise terms are commercial. Separate
  repositories keep licensing, access control, and release cadence clean.
- A versioned dependency forces the OSS contracts to stay genuinely stable — the boundary is
  exercised by real consumption, not by folder conventions.
- Enterprise-only code can never leak into the public repository, and OSS contributors never need
  Enterprise access.

## Alternatives considered

1. **Monorepo with an open-core boundary** (packages/datahek-core + packages/datahek-enterprise).
2. **Full fork**: Enterprise as a permanently diverged copy of OSS.

## Why alternatives were rejected

- Monorepo: acceptable at the start, but it mixes license scopes and couples the release cadence;
  it was the earlier recommendation and was superseded by the final decision.
- Fork: every bug and security fix would have to land twice — the failure mode the foundation
  review explicitly warned about (Risk 1).

## Consequences

- OSS must build, test, and run with no Enterprise repository present. This is verified by CI on
  this repository alone.
- OSS defines stable contracts (`src/datahek/contracts/`) and extension points (DI container,
  extension registry). Enterprise depends on tagged OSS releases, not branches.
- OSS publishes contract tests that Enterprise implementations must pass.

## Migration strategy

Not applicable — this decision was taken before the Enterprise repository was created.

## Revisit conditions

- The Enterprise codebase grows large enough that its release process must be fully independent.
- Release synchronization between the two repositories becomes a recurring operational cost.
- Legal or compliance requirements force a different distribution split.
