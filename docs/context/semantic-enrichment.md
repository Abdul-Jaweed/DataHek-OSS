# Context Layer — Semantic Enrichment

**Status:** Milestone 5 deliverable
**Related:** FR-004 · ADR-008 · ADR-013

Enrichment is the **only LLM stage** in the Context Layer build path. Its job: propose business
meaning (concepts, relationships, descriptions, synonyms) that rules cannot derive. It never
becomes the source of truth.

## Hybrid pipeline

| Stage | Author | Authority |
|---|---|---|
| Schema, statistics, roles, topology, grain | code (deterministic) | `SYSTEM` / `DATABASE`, `STRUCTURAL` trust |
| Concepts, relationships, descriptions, synonyms | `ModelProvider` (LLM) | `LLM` provenance, `PROPOSED` trust, `PENDING` validation |
| Approve / edit / reject | human (M9) | `HUMAN_VALIDATED`, authoritative |

## Inputs and outputs

`OntologyEnricher(model).propose(schema, taxonomy, *, metrics=()) -> OntologyContext`

- **Input to the model**: table names with `column:type` lists, plus metric definitions when
  available. No row data, no sample values, no credentials.
- **Output**: JSON concepts/relationships, schema-grounded and vocabulary-checked before emission
  (see [ontology.md](ontology.md)).

## Rules

1. **Proposals only.** Every field carries `validation=PENDING`; retrieval may include proposals
   as clearly-marked untrusted context, never as instructions.
2. **Graceful failure.** Model errors and parse failures yield an empty ontology with warnings;
   deterministic context still publishes (SRD FR-004, failure-mode table).
3. **No silent authority.** A proposal never overwrites a human-validated artifact; corrections
   outrank LLM output permanently (ADR-008).
4. **Re-proposal discipline.** Validated decisions are excluded from future proposal prompts, so
   humans are not asked the same question twice (M9 enforces the filter).
5. **Prompt-injection posture.** Descriptions/synonyms are untrusted text; instruction separation
   applies wherever they enter an agent prompt.

## Cost and scheduling

Enrichment runs inside the build job (M8) after deterministic stages, is skippable
(`enrichment=False`), and is retryable independently — an unavailable model defers enrichment
without invalidating the build.

## Tests

`tests/test_context_enrichment.py` — controlled-vocabulary filtering, schema grounding, dangling
reference rejection, malformed JSON, and model failure.
