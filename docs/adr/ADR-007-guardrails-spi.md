# ADR-007: Guardrails SPI

**Status:** Accepted (native pipeline implemented; external adapters future)

## Context

DataHek's trust model depends on guardrails that are database-aware: read-only enforcement, SQL
plan validation, injection detection, PII masking, rate limits, and human approval. Generic
conversational guardrail frameworks (NeMo Guardrails, Guardrails AI, Llama Guard, AWS Bedrock
Guardrails) cannot replace database-level safety, but they can add value in specific lanes.

## Decision

DataHek owns a small **native guardrails SPI** and treats external frameworks as optional adapters:

- `Guardrail` contract (`src/datahek/contracts/guardrails.py`): `name`, `stage`, `enabled`, and
  `run(ctx, payload) -> GuardrailResult`.
- Typed decisions: `ALLOW`, `DENY`, `REDACT`, `MASK`, `REQUIRE_APPROVAL`, `RATE_LIMIT`. Expected
  policy outcomes are typed results; exceptions are reserved for infrastructure failures.
- Stages: `input`, `plan`, `sql`, `output`. The pipeline runs in order; the first non-ALLOW
  decision wins.
- Policy decisions come from a `PolicyEngine` (`LocalPolicyEngine` in OSS); the pipeline only
  enforces them. This keeps authorization logic out of the guardrail classes.
- External frameworks are **never hard dependencies**; each would be integrated as an adapter
  behind the same SPI.

## Why this decision

- Database safety is domain logic: SQL plans must be parsed, tables authorized, results masked, and
  credentials kept away from the model.
- A typed decision contract makes behavior testable and auditable (each decision is recorded).
- Adapter-based integration avoids framework coupling, latency, and inconsistent behavior across
  surfaces.

## Alternatives considered

1. Depend on one complete framework (NeMo, Guardrails AI, Llama Guard, or Bedrock) as the pipeline.
2. No formal SPI — ad-hoc checks scattered across the API and engine.

## Why alternatives were rejected

- Single framework: none replace SQL parsing, table authorization, or execution controls; each
  introduces cloud or model coupling.
- Ad-hoc checks: the failure mode the foundation review flagged (middleware becoming an
  unmaintainable pile). Typed decisions and a policy engine prevent it.

## Consequences

- Guardrail decisions are audited (`guardrail.decision` events) with policy version.
- The same pipeline protects API, CLI, MCP, and the scheduler — no privileged bypass.
- Adapters for external frameworks are future work; the SPI is the integration point.

## Migration strategy

Adapters are additive; the native pipeline remains the default in every edition.

## Revisit conditions

- An evaluation demonstrates an external classifier materially improves safety for a specific
  threat, at acceptable latency.
