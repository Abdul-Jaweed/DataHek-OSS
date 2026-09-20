# Context Layer — Provenance

**Status:** Milestone 8 deliverable
**Related:** ADR-008 (human validation) · ADR-013 (LLM vs deterministic) · SRD FR-004/FR-010

Every artifact, record, and graph element states where it came from, how confident it is, and
whether a human has reviewed it. Provenance is a field, not a convention.

## Sources

| Source | Produced by | Trust |
|---|---|---|
| `DATABASE` | introspection, profiling, FK topology | `STRUCTURAL` |
| `SYSTEM` | deterministic rules (taxonomy, grain, inferred joins, metrics) | `SYSTEM`/`STRUCTURAL` |
| `LLM` | ontology enrichment (concepts, relationships, descriptions) | `PROPOSED` |
| `USER` | API/UI input (e.g. metric definitions) | `PROPOSED` |
| `HUMAN_VALIDATED` | approve/edit after review (M9) | `VALIDATED` |
| `INFERRED` | heuristic join inference | `UNTRUSTED`-adjacent, confidence-scored |
| `IMPORTED` | external catalogs/glossaries (future) | `PROPOSED` |

Trust ordering (`context/provenance.py`): `SYSTEM > VALIDATED > STRUCTURAL > PROPOSED >
UNTRUSTED`. A package's trust is the **minimum** of its included content; `can_override` encodes
that human validation outranks LLM output permanently.

## Validation status

- Artifact envelopes and ontology items carry `validation` (`NOT_REQUIRED`, `PENDING`, `APPROVED`,
  `EDITED`, `REJECTED`).
- Deterministic artifacts are `NOT_REQUIRED`; rule-derived artifacts (taxonomy, grain, topology)
  are `PENDING` (humans confirm them); LLM proposals are `PENDING` until reviewed.
- M9 adds the approve/edit/reject workflow; corrections become `HUMAN_VALIDATED` records via a new
  version, and validated decisions are excluded from future re-proposal prompts.

## Recorded where

- **Artifacts**: `envelope.provenance`, `envelope.trust`, `envelope.validation`,
  `envelope.confidence`, per-item provenance on ontology/taxonomy/grain items.
- **Registry records**: `provenance_summary` counts artifacts per source (e.g. `{"database": 3,
  "system": 2, "llm": 1}`) plus `validation` timestamps.
- **Packages**: `provenance` entries per field/section, package-level `trust`, and `degraded`
  sections.
- **Graph**: every node/edge stores `provenance` (and `confidence` on edges), so graph reads can
  distinguish structural facts from proposals.

## Rules

1. LLM output is **data, never instructions** — descriptions/synonyms cannot alter governance or
   behavior until human-validated.
2. Proposals never overwrite validated content; they coexist as separate, clearly-marked items.
3. Deterministic facts are recomputed, not trusted from cache, when a schema hash changes.
4. Fail closed: unknown sensitivity or unverifiable provenance downgrades trust, never upgrades it.
