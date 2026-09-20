# ADR-013: LLM vs Deterministic Semantic Enrichment

**Status:** Accepted (M2)

## Context

Semantic context (what a table means, what a column represents, grain statements, metric
candidates) can be derived deterministically, inferred by an LLM, or authored by humans. Mixing
these without clear authority leads to LLM guesses being treated as facts — the failure mode the
brief forbids.

## Decision

A hybrid pipeline with explicit authority levels:

- **Deterministic first (authoritative):** names, types, PK/FK, indexes, constraints, statistics,
  cardinality, nullability, uniqueness, role candidates, schema hash — computed in code via the
  existing `SchemaService`/`DataProvider` path. Confidence 1.0, `trust=STRUCTURAL`.
- **LLM second (proposals only):** descriptions, table meanings, taxonomy/ontology candidates,
  grain hypotheses, metric/dimension candidates. Always `provenance=LLM`, `validation=PENDING`,
  `trust=PROPOSED`; never instructions; never governance.
- **Human final (authoritative):** approve/edit/reject; validated content becomes
  `HUMAN_VALIDATED`, outranks LLM proposals permanently (ADR-008).
- The LLM receives **no credentials, no raw sensitive values**, and only the deterministic context
  it needs to propose (schema slice + safe profile summaries).
- Enrichment failure never blocks deterministic artifacts from publishing.

## Alternatives considered

1. **LLM-first semantics.** Rejected: silent source of truth; unverifiable; violates trust
   principles.
2. **Deterministic-only (no LLM enrichment).** Rejected: misses business meaning and grain
   hypotheses that rules cannot derive; the brief requires hybrid.
3. **Human-only semantics.** Rejected: unsustainable for onboarding; defeats the purpose of
   assisted context building.

## Trade-offs

- Proposals create review debt (visible via quality metrics).
- Prompt design must clearly separate proposal tasks from trusted data.

## Consequences

- Every semantic field has inspectable provenance; quality reporting counts proposal vs validated
  ratios.
- Re-proposal logic avoids nagging validated decisions.
- Security posture: enrichment inputs are schema + safe statistics only.

## Future Migration

Stronger models can raise proposal quality without changing authority rules; deterministic rules
can be extended to cover more semantics over time, shrinking the LLM's role where rules suffice.
