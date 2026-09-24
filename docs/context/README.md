# DataHek Context Layer

The Context Layer is a first-class DataHek subsystem: it produces the minimum relevant, trustworthy,
governed, versioned, task-appropriate information an agent needs to answer correctly — as structured
artifacts, not prose. A system prompt is one consumer of context, not the context itself.

```
Persistent Context → Retrieval → Selection → Composition → Compilation → Context Package → Agent → LLM
```

## Status

| Milestone | Deliverable | State |
|---|---|---|
| M1 | Repository analysis + research | **Complete** |
| M2 | Architecture, context model, SRD, ADRs, diagrams | **Complete** |
| M3 | Context domain model + contracts | **Complete** |
| M4 | Schema discovery + profiling | **Complete** |
| M5 | Taxonomy, ontology, topology, granularity | **Complete** |
| M6 | Graph abstraction + Neo4j adapter | **Complete** |
| M7 | Schema Knowledge Graph | **Complete** |
| M8 | Context Registry, persistence, versioning | **Complete** |
| M9 | Human semantic validation | **Complete** |
| M10 | Retrieval, composer, compiler | **Complete** |
| M11 | SQL agent integration | **Complete** |
| M12 | Testing, observability, security hardening | **Complete** |

## Documents

- [`repository-analysis.md`](repository-analysis.md) — where the Context Layer integrates, what it
  reuses, conflicts, and recommended boundaries (M1)
- [`research.md`](research.md) — context-engineering vocabulary, agent context architecture,
  database semantics, taxonomy/ontology/topology/granularity, profiling, schema KG, graph database
  comparison (M1)
- [`architecture.md`](architecture.md) — components, contracts, package layout, six Mermaid
  diagrams, error/degradation table, security boundaries, observability (M2)
- [`context-model.md`](context-model.md) — enumerations, registry record, artifact schemas,
  `ContextPackage`, quality/freshness reports, versioning rules (M2)
- [`context-layer-srd.md`](context-layer-srd.md) — purpose, scope, 20 functional requirements with
  acceptance criteria, 10 NFRs, 12 failure modes, milestone traceability (M2)
- [`topology.md`](topology.md) — FK/inferred edges, cardinality, bounded join paths (M5)
- [`granularity.md`](granularity.md) — table and metric grain statements (M5)
- [`taxonomy.md`](taxonomy.md) — role-based classification hierarchy (M5)
- [`ontology.md`](ontology.md) — concepts, controlled relationship vocabulary, proposal rules (M5)
- [`semantic-enrichment.md`](semantic-enrichment.md) — the single LLM stage, trust and failure
  behavior (M5)
- [`schema-profiling.md`](schema-profiling.md) — deterministic profiling method and privacy rules (M4)
- [`graph-abstraction.md`](graph-abstraction.md) — the replaceable graph contract and its shared
  test suite (M6)
- [`neo4j.md`](neo4j.md) — Neo4j deployment, schema, safety rules, and licensing notes (M6)
- [`knowledge-graph-schema.md`](knowledge-graph-schema.md) — node/edge catalogue, id scheme,
  idempotency/pruning, degraded behavior, example reads (M7)
- [`lifecycle.md`](lifecycle.md) — states, legal transitions, publish ordering, invalidation,
  build-job mapping (M8)
- [`provenance.md`](provenance.md) — sources, trust levels, validation status, recording points,
  rules (M8)
- [`validation.md`](validation.md) — reviewable items, decisions, quality effect, re-proposal
  discipline (M9)
- [`context-retrieval.md`](context-retrieval.md) — deterministic bounded selection, caps, stale
  signaling (M10)
- [`context-composition.md`](context-composition.md) — budget model, ordered degradation,
  deterministic compilation, trust floor (M10)
- [`api.md`](api.md) — context REST endpoints, planner integration rules, deferred items (M11)
- [`security.md`](security.md) — credential/sensitive-value hygiene, tenant isolation, untrusted
  content, failure paths (M12)
- [`multi-tenancy.md`](multi-tenancy.md) — ownership model and enforcement points (M12)
- [`observability.md`](observability.md) — metrics catalogue, audit events, non-goals (M12)
- [`testing-strategy.md`](testing-strategy.md) — test levels, conventions, FR→test coverage map
  (M12)
- [`context-layer-overview.md`](context-layer-overview.md) — consolidated how-it-works guide:
  architecture, artifact catalogue, build/runtime sequencing, guarantees, evidence
- [`context-layer-deck.html`](context-layer-deck.html) — self-contained presentation deck
  (open in a browser, arrow keys to navigate, print to PDF)

Since M12, the subsystem also ships: **background rebuild queue** (deduplicated, tenant-scoped,
`GET /context/rebuilds`), **scoped records** (`scope=connection|schema|table` + `tables` filter),
**package persistence** (`/contexts/{id}/package`), **configurable caps/budget** (env +
per-request `budget_tokens`), **profiler value hints** for low-cardinality non-sensitive columns,
and an OSS web **Context page** with a review inbox (`/context`).
- [`schema-knowledge-graph.md`](schema-knowledge-graph.md) — **single source of truth** for how the Context Layer uses Neo4j to build, store, retrieve, and operationalize its Schema Knowledge Graph: graph fundamentals, taxonomy/ontology/topology/granularity, the complete Neo4j model, Cypher cookbook, performance/security/observability, storage architecture, and the final recommended architecture (~55 Mermaid diagrams, ~45 Cypher recipes)
- [`ADR/`](ADR/) — 13 architecture decision records (subsystem boundary, persistent vs runtime,
  schema KG, Neo4j, graph abstraction, registry, package model, human validation, freshness, change
  detection, storage split, multi-tenancy, LLM vs deterministic)

M3 delivered in code: `contracts/context.py` (all enums, artifact schemas, `ContextPackage`,
`ContextRecord`, graph models, and the `ContextRegistry`/`ContextStore`/`GraphRepository`
protocols), `context/lifecycle.py` (legal-transition state machine), `context/hashing.py`
(canonical SHA-256 schema hashing), `context/provenance.py` (trust ordering and authority rules) —
with 25 tests across the four modules.

M4 delivered in code: constraint-aware introspection (`ColumnMeta`/`TableMeta` PK/FK/index/
nullability/default fields; SQLite PRAGMA and PostgreSQL information_schema capture),
`context/snapshot.py` (catalog → canonical `SchemaContext` + hash), and `context/profiler.py`
(one batched aggregate plan per table through the guarded engine; null/distinct/uniqueness,
min/max/avg, role candidates, sensitive-column counts-only policy) — see
[`schema-profiling.md`](schema-profiling.md).

M5 delivered in code: `context/topology.py` (FK edges, `<entity>_id` inference with type-family
checks, depth-bounded join paths), `context/granularity.py` (grain statements from PK +
identifier profiles, metric-grain caveats), `context/taxonomy.py` (role-based
Domain → Subdomain → Category hierarchy, sensitive columns excluded), and `context/enrichment.py`
(LLM concept/relationship proposals with controlled vocabularies, schema grounding, and graceful
failure).

M6 delivered in code: `context/graph/vocabulary.py` (ADR-003 controlled relationship types),
`context/graph/memory.py` (deterministic adapter), `context/graph/neo4j.py` (Cypher confined here;
tenant-scoped, vocabulary-validated, MERGE-idempotent, bounded reads), a shared
`GraphRepositoryContract` suite that both adapters pass against live instances, the optional
`[graph]` extra, container registration behind `DATAHEK_NEO4J_URL`, and a compose `graph` profile.

M7 delivered in code: `context/graph/builder.py` — projects schema, profile, topology (FK and
inferred joins), granularity, taxonomy annotations, metrics, and ontology into the graph with
stable ids, vocabulary-only edges, version/provenance stamps, idempotent rebuilds, per-connection
pruning, and `DEGRADED` reports when the backend is unavailable. Verified live against Neo4j with
the InsForge artifacts (48 nodes, 47 edges, idempotent, ~30 ms reads).

M8 delivered in code: typed JSON serialization (artifacts, records, packages), quality and
freshness evaluators, SQLite and PostgreSQL `ContextRegistry`/`ContextStore` (PG migration v2)
with tenant-scoped reads, `ContextRegistryService` publish/version/supersede/invalidate through
the lifecycle state machine, and the staged `ContextBuildJob` (introspect → profile → topology →
granularity → taxonomy → enrich → graph → quality → publish) with retries, degradation, and
skip-if-current. Verified live: InsForge ACTIVE v1 → `current` → rebuild v2 SUPERSEDED.

M9 delivered in code: `context/validation.py` (pending-items listing and approve/edit/reject
decisions that publish a new `HUMAN_VALIDATED` version), `active_artifact` on the registry
service, enricher `validated=` priors wired through the build job so reviewed items are never
re-proposed, and a corrected `human_validation` quality dimension that counts all reviewable
items (ontology, taxonomy, grain).

M10 delivered in code: `context/retriever.py` (deterministic question-token selection with table/
column caps, join-edge and slice filtering, governance pass-through, stale flag),
`context/composer.py` (token-budget composition with the documented drop order and metric
relevance pruning), `context/compiler.py` (deterministic `ContextPackage` with semantics summary,
trust floor, and fail-closed insufficient override), and container registration of the
`ContextRetriever`/`ContextComposer`/`ContextCompiler` protocols. Verified live against InsForge:
selection → 995-token composition → `structural`-trust package; 1-token budget produced an
`INSUFFICIENT` package with `reason=budget`.

M11 delivered in code: planner integration (`Planner` takes the retriever/composer/compiler;
compiled packages replace the ad-hoc schema/metric assembly, `INSUFFICIENT` fails closed with a
clarification, and any context-layer failure degrades to the live catalog — FR-019/FR-020), the
context REST surface in `api/app.py` (status, synchronous build, versions, pending, validate,
preview, record detail), container registration of `ContextValidationService` and
`ContextBuildJob`, and `docs/context/api.md`. Verified live against InsForge through an in-process
TestClient: build → preview (995 tokens, `structural`) → 9 pending → approval v2 → `POST /ask`
answered from context-compiled planning.

M12 delivered in code: `CONTEXT_UNAVAILABLE` (503) with reason details for store failures, context
metrics (`builds`, `retrievals` by outcome, durations, tokens, `insufficient`, `validations`) on
`/metrics`, cross-tenant/credential-hygiene/injection security tests, end-to-end degradation tests
for `/ask` (retriever failure → live catalog; insufficient package → clarification), and the
`security.md` / `multi-tenancy.md` / `observability.md` / `testing-strategy.md` specifications.
All twelve milestones of the Context Layer brief are complete: **695 tests, 54 env-gated skips**.

Subsystem specifications (all delivered): `taxonomy.md` / `ontology.md` / `topology.md` /
`granularity.md` / `semantic-enrichment.md` (M5), `graph-abstraction.md` / `neo4j.md` /
`knowledge-graph-schema.md` (M6–M7), `lifecycle.md` / `provenance.md` (M8),
`context-retrieval.md` / `context-composition.md` (M10), `api.md` (M11), `security.md` /
`multi-tenancy.md` / `observability.md` / `testing-strategy.md` (M12).

## Non-goals (V1)

No data-level knowledge graph, no vector database / RAG platform, no autonomous agent swarm, no
unrestricted Cypher or SQL generation from LLM output, no credentials in context, no entire-graph
injection into prompts, no Neo4j-specific domain model.
