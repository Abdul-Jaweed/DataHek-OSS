# ADR-007: Context Package Model

**Status:** Accepted (M2)

## Context

The LLM must receive relevant structured context — not the entire store, not one giant JSON blob
without boundaries. Consumers beyond the planner (verifier, explainer, analyst, MCP) will need
different slices. Without a canonical package, each consumer reinvents selection and budget logic.

## Decision

Define a canonical, immutable **`ContextPackage`** (see [context-model.md](../context-model.md) §4)
produced by the compiler for one `purpose`:

- Identity and versioning: `context_id`, `version`, `schema_hash`, `purpose`, `generated_at`.
- Relevant slices only: schema, profile, taxonomy, ontology, topology, granularity — never whole
  catalogs.
- Semantics summary (validated metrics/dimensions/identifiers/temporal fields), governance,
  capabilities.
- Quality, freshness, provenance, and a package-level **trust level** (minimum of included
  content).
- Budget metadata: estimated tokens and `dropped_sections` (ordered degradation record).

Rules: governance and granularity are never dropped by budgeting (insufficient ⇒ fail closed);
packages are immutable and keyed by `(context_id, version, purpose, retrieval_digest)`; byte-
identical outputs for identical inputs.

## Alternatives considered

1. **Free-form dict assembled per consumer.** Rejected: unverifiable, untestable, no budget
   discipline, provenance lost.
2. **One giant package containing everything for every purpose.** Rejected: token waste, trust
   dilution, brittle prompts.
3. **Send raw artifacts directly to the LLM.** Rejected: leaks unreviewed/proposed content and
   violates the trust boundary.

## Trade-offs

- Package schema becomes a maintained contract (additive changes with `schema_version`).
- Compiler complexity (selection, budgeting, degradation) moves into one place — which is the
  point.

## Consequences

- Determinism is testable: fixed inputs produce identical packages.
- Provenance and trust travel with the data into downstream reasoning and auditing.
- New purposes (`sql.verifier`, `mcp.tool`) add sections without changing the core shape.

## Future Migration

If semantic/vector retrieval arrives later (V3 roadmap), it enriches selection inputs; the package
shape remains valid. New sections are additive.
