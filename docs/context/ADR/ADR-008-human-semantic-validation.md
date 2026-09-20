# ADR-008: Human Semantic Validation

**Status:** Accepted (M2)

## Context

LLM-proposed semantics (descriptions, meanings, grain hypotheses, metric candidates) are useful
but fallible. The brief forbids the LLM silently becoming the source of truth: "The LLM proposes
semantics; trusted systems and humans validate them." The canonical acceptance scenario ends with
a human confirming "one row represents one order."

## Decision

Every semantic proposal carries `provenance` and `validation` status, and enters a review
workflow:

- `PENDING` proposals are usable only as untrusted, clearly-marked context (never as instructions,
  never as governance).
- Validation operations: **approve**, **edit** (with corrected content), **reject** (with reason).
- Approved/edited proposals become `HUMAN_VALIDATED` trusted context, bump the context version,
  and are excluded from future re-proposal churn.
- Human corrections are **authoritative over LLM output** permanently until superseded by another
  human edit.
- Validation is exposed through typed API operations and audited (`context_validated` events with
  actor and decision). A UI surface is a later milestone; the contract comes first.

Validation prompts are phrased as understanding checks ("I interpreted your table as follows. Is
this correct?"), not system-prompt reviews.

## Alternatives considered

1. **Auto-accept LLM semantics.** Rejected: violates the trust principle; wrong grain/metrics
   silently corrupt answers.
2. **Block on validation always.** Rejected: unusable for OSS single-user quickstarts; proposals
   with clear marking are safe to proceed with.
3. **Only humans author semantics (no LLM).** Rejected: misses the value of automated proposals and
   the brief explicitly wants hybrid enrichment.

## Trade-offs

- Requires workflow surface and storage for validation history (registry versioning covers it).
- Stale pending proposals create review debt; quality report makes that visible.

## Consequences

- Context quality distinguishes deterministic, proposed, and validated content per dimension.
- Re-proposal logic must respect validated decisions (no nagging drift).
- Enterprise can later add approval chains without changing the model.

## Future Migration

Group-based approvals, policy-driven auto-validation for low-risk artifacts, and validation SLAs
are additive to the same status model.
