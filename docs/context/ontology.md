# Context Layer — Ontology

**Status:** Milestone 5 deliverable
**Related:** FR-006 · ADR-008 · ADR-013 · research.md §4

Ontology answers **"what things exist and how do they relate?"** — concepts and typed
relationships, proposed by the LLM, validated against the schema, and never authoritative until a
human approves them.

## Model

`OntologyContext` = concepts + relationships:

- **Concepts**: `name`, `kind` (`entity` | `value`), `maps_to` (tables), `attributes`
  (`table.column`), `description`, `synonyms` — e.g. `Order` → `orders`, meaning "a customer order",
  synonym "purchase".
- **Relationships**: `subject`, `predicate`, `object`, `kind` from the controlled vocabulary:
  `places`, `contains`, `belongs_to`, `has_amount`, `has_status`, `occurs_at`, `identifies`,
  `measures`, `relates_to`.

Controlled vocabularies are code constants (`CONCEPT_KINDS`, `RELATIONSHIP_KINDS`); adding a new
kind is a deliberate change, not an LLM decision.

## Validation before emission

Every proposal passes schema-grounding checks; anything failing is dropped, not stored:

1. Concept kind must be in the controlled set; at least one `tables` entry must exist in the
   schema.
2. `attributes` must resolve to real `table.column` pairs.
3. Relationship kind must be controlled; subject/object must reference a surviving concept or a
   real table (dangling references are dropped).
4. Everything emitted is `provenance=LLM`, `trust=PROPOSED`, `validation=PENDING`, confidence 0.6.

## Trust boundary

LLM output is **data, never instructions**: descriptions and synonyms are stored as untrusted
content, cannot influence governance, and are excluded from authoritative decisions until human
validation promotes them (`HUMAN_VALIDATED`). The prompt receives only schema names/types and
metric definitions — no data values, no credentials.

## Failure behavior

Model unavailable, rate-limited, or returning unparseable output ⇒ `OntologyContext` with empty
concepts/relationships, `trust=UNTRUSTED`, `confidence=0.0`, and a `warnings` entry. Deterministic
artifacts are never blocked by enrichment failure (SRD FR-004).

## Tests

`tests/test_context_enrichment.py` (4): parsing and filtering (including dangling references and
unknown kinds), invalid attribute rejection, malformed-JSON grace, model-failure grace.
