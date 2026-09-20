# Context Layer — Human Semantic Validation

**Status:** Milestone 9 deliverable
**Related:** FR-010 · ADR-008 (humans outrank LLMs) · [provenance.md](provenance.md) · [lifecycle.md](lifecycle.md)

Validation is the review gate between machine-generated context and trusted context. The LLM
proposes; deterministic rules derive; **humans confirm**. No proposal silently becomes
authoritative.

## Reviewable items

| Artifact | Section | Items | Editable fields |
|---|---|---|---|
| Ontology | `concepts` | LLM concepts | `description`, `synonyms` |
| Ontology | `relationships` | LLM relationships | `predicate` |
| Taxonomy | `nodes` | rule-derived nodes | — (approve/reject) |
| Granularity | `grains` | rule-derived grain statements | `statement`, `qualifier`, `entity` |

Items are addressed by `(kind, section, index)` against the **active version** — versions are
immutable, so indices are stable within a review pass.

## Service

`ContextValidationService(registry, store, registry_service)`:

- `list_pending(ctx, connection_id, scope="connection") -> list[PendingItem]` — every item with
  `validation=PENDING`, with label, provenance, and confidence for the review surface.
- `apply(ctx, connection_id, scope, decisions) -> ContextRecord` — applies
  `ValidationDecision(kind, index, action, section="", patch=None)` where `action ∈
  {approve, edit, reject}` and publishes a **new version**.

Effects:

| Action | Result |
|---|---|
| `approve` | `validation=APPROVED`, provenance/source → `HUMAN_VALIDATED` |
| `edit` | patch applied (whitelist enforced), `validation=EDITED`, provenance → `HUMAN_VALIDATED` |
| `reject` | `validation=REJECTED`, provenance unchanged (still traceable to its origin) |

Invalid actions, unknown sections, out-of-range indices, non-editable fields, and empty decision
sets raise `VALIDATION`; a missing active record raises `NOT_FOUND`. Nothing is mutated in place —
the reviewed version stays intact and a new `context_id` supersedes it.

## Quality effect

`QualityReport.human_validation` counts **all reviewable items** (ontology, taxonomy, grain):
validated ÷ reviewable. Builds without proposals score 1.0; a build with nine pending items scores
0.0 until reviewed. Rejections count as reviewed, not validated.

## Re-proposal discipline

Validated items are passed to the next enrichment run as fixed priors — the enricher prompt lists
them under "Already validated (treat as fixed, do not re-propose)". The build job loads them from
the active ontology artifact, so humans are never asked the same question twice (ADR-008).

## Deferred

- REST/UI surfaces for the review inbox (M10/M11 integration).
- Per-actor attribution and audit events for decisions (M12 observability).
- Structural edits (re-wiring relationships, splitting concepts) — approve/reject plus text edits
  are the V1 boundary.

## Tests

`tests/test_context_validation.py` (9): pending listing across artifact kinds, approve/edit/reject
effects and provenance flips, validated-version publishing with supersede, quality recomputation,
and input-validation failures. Enricher priors covered in `tests/test_context_enrichment.py`;
job wiring in `tests/test_context_build_job.py`.

## Live evidence

InsForge build (deterministic only): ACTIVE v1 with **9 pending items** (7 taxonomy nodes,
2 grains) and `human_validation=0.0`; approving one taxonomy node and editing one grain statement
published **v2 ACTIVE** with `human_validation=0.2222` and the grain carrying
`edited / human_validated`.
