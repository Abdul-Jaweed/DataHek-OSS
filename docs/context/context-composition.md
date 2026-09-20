# Context Layer — Composition and Compilation

**Status:** Milestone 10 deliverable
**Related:** FR-013 · ADR-007 (package model) · [context-model.md](context-model.md) · [provenance.md](provenance.md)

Composition merges the retrieved subset under a token budget with **ordered degradation**;
compilation emits a deterministic `ContextPackage` for the `sql.planner` purpose. Same inputs
produce byte-identical packages, and the pipeline fails closed when governance cannot be included
(FR-013).

## Composer

`BudgetContextComposer.compose(ctx, retrieved, runtime, budget_tokens=4000) -> ComposedContext`

- **Cost model.** `estimate_tokens(value) = len(str(value)) // 4` — deterministic and monotonic in
  section size, not a model tokenizer.
- **Mandatory sections.** `schema`, `governance`, `granularity` are always attempted first. If
  they alone exceed the budget, composition returns with `insufficient_reason="budget"` — it does
  not silently drop governance or grain.
- **Optional drop order.** When over budget, sections are dropped in the documented order:
  `profiles → taxonomy → topology → ontology → metrics`. Empty sections are simply absent, not
  recorded as dropped.
- **Metric relevance pruning.** Before dropping the whole metrics section, metrics with zero token
  overlap with the runtime question are pruned; if the relevant remainder fits, it is kept.

The result records `dropped`, `tokens_estimate`, and `insufficient_reason` on the
`ComposedContext`.

## Compiler

`PackageContextCompiler.compile(ctx, composed, quality, freshness, governance=None, skills=(),
tools=(), providers=()) -> ContextPackage`

- **Semantics summary.** Dimensions, identifiers, and temporal fields come from taxonomy
  `Dimension`/`Identifier`/`Temporal` categories; when taxonomy is absent, profile role candidates
  are used instead. Metrics are carried through as-is.
- **Trust floor.** `package.trust` is the minimum effective trust of included content
  (`provenance.effective_trust` over governance, schema, and each present artifact). An included
  LLM-proposed ontology therefore lowers the package to `PROPOSED`.
- **Governance.** Uses the composed governance when present, otherwise synthesizes a
  `SYSTEM`-trusted OSS-local governance block with `allowed_operations=("SELECT",)`.
- **Degradation.** `composed.dropped` becomes `package.degraded` and
  `package.budget.dropped_sections`; an `insufficient_reason` overrides
  `quality.state=INSUFFICIENT` with the reason recorded in `quality.details` so consumers fail
  closed.
- **Capabilities.** Skill/tool/provider references are attached as a `CapabilityContext` with a
  `SYSTEM` envelope.

## Wiring

`build_default_container` registers the `ContextRetriever`, `ContextComposer`, and
`ContextCompiler` protocols alongside `ContextRegistryService`; the retriever receives the
configured `SemanticStore` for metric matching.

## Tests

`tests/test_context_composition.py` (11): full-budget retention, documented drop order at a tuned
budget, impossible budget → `INSUFFICIENT`, composition determinism, semantics from taxonomy and
from profile-role fallback, trust floor with/without ontology, degradation propagation,
insufficient quality override, capability passthrough, compilation determinism.

## Live evidence

InsForge (deterministic build): composed 995 tokens with no drops; a 1-token budget returned
`insufficient_reason="budget"` and the compiled package carried
`quality.state=insufficient, reason=budget`; normal compilation produced
`trust=structural` with `degraded=()`.
