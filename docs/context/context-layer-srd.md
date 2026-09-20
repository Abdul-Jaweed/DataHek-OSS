# Context Layer — Software Requirements Document (SRD)

**Status:** Milestone 2 deliverable — proposed for review
**Scope:** V1 of the DataHek Context Layer (SQL-first; no vector/RAG architecture)

---

## 1. Purpose

DataHek agents currently receive an ad-hoc assembly of schema text, metric definitions, and
conversation history. That works for small schemas and breaks down for wide tables, large
catalogs, and questions that depend on grain, joinability, or business meaning. The Context Layer
exists to provide **the minimum relevant, trustworthy, governed, versioned, task-appropriate
information** an agent needs — as versioned structured artifacts built ahead of time, retrieved
per request, and compiled into a deterministic package for the LLM. A system prompt becomes one
consumer of context, not the context itself.

## 2. Scope

**In scope (V1):** schema discovery and canonical snapshots; deterministic privacy-aware
profiling; LLM semantic enrichment as proposals; taxonomy, ontology, topology, and granularity
artifacts; governance and capability artifacts; Schema Knowledge Graph behind a replaceable graph
abstraction (Neo4j first); human validation; context registry, store, versioning, lifecycle,
freshness, and invalidation; retrieval, composition, and compilation for the SQL planner;
asynchronous staged build jobs; observability, security, and tests.

**Out of scope (V1):** data-level knowledge graphs; vector databases and semantic/embedding
retrieval; autonomous context-curating agents; unrestricted Cypher/SQL generation from LLM output;
credentials or raw sensitive values in context; injecting the whole graph into prompts; persistent
runtime context; job-queue infrastructure beyond the existing patterns; non-SQL context sources.

## 3. Functional requirements

Each FR lists an acceptance criterion that can be tested.

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-001 | **Database schema discovery.** Build a canonical schema snapshot per scope using the existing `SchemaService`/provider introspection; never raw catalog SQL assembled from context. | Snapshot contains tables, columns, types, nullability, PK/FK, indexes for the selected scope; deterministic across runs; `schema_hash` stable for identical schemas |
| FR-002 | **Table selection.** Context scopes are configurable (whole connection or explicit table list) and bounded by entitlements; selection is recorded in the context record. | Building with a 5-table selection produces artifacts containing exactly those tables (plus relationship edges touching them) |
| FR-003 | **Schema profiling.** Deterministically compute row count, null ratio, distinct count, uniqueness ratio, min/max/avg, and ranked candidate roles through the guarded engine; sensitive columns get counts only. Text length ranges and top-k value buckets are deferred until the plan model supports expressions (see `schema-profiling.md`). | Profiles match direct SQL aggregates on the same data; a forced per-column error yields a recorded coverage gap, not a job failure |
| FR-004 | **Semantic enrichment.** LLM proposes descriptions, table meanings, metric/dimension candidates, and grain hypotheses; all proposals are `pending_validation` and never authoritative. | Every LLM-derived field has `provenance=LLM`, `validation=PENDING`; enrichment failure leaves deterministic artifacts publishable |
| FR-005 | **Taxonomy generation.** Classify tables/columns into Domain → Subdomain → Entity → Attribute categories from a controlled vocabulary, merging deterministic role candidates with proposals. | Taxonomy artifact validates against the model; every member resolves to a real column; conflicting proposals are marked and queue for validation |
| FR-006 | **Ontology generation.** Produce concepts/entities and typed relationships (`places`, `contains`, `belongs_to`, `has_amount`, `occurs_at`, `identifies`) with provenance and confidence. | Ontology relationships reference existing concepts; no relationship type outside the controlled vocabulary is emitted |
| FR-007 | **Relationship discovery (topology).** Emit FK edges (confidence 1.0) and inferred join candidates with cardinality estimates, plus bounded join paths (max depth 3) between selected tables. | FK edges match catalog constraints; inferred edges are marked `INFERRED` with confidence; join paths never exceed depth 3 |
| FR-008 | **Granularity detection.** Produce table grain statements and metric-grain validity with explicit caveats (e.g., double-count risk). | Every selected table has a grain statement or an explicit "unknown" marker; metric grains reference existing metrics |
| FR-009 | **Schema Knowledge Graph.** Project validated and proposed context into a tenant-scoped graph with the controlled node/relationship vocabulary; graph is optional and never blocks registry/store. | Nodes/edges carry `org_id`, `context_version`, `schema_hash`; graph queries return only the ACTIVE version; with Neo4j stopped, builds succeed in `DEGRADED` state |
| FR-010 | **Human validation.** Proposals can be approved, edited, or rejected through typed operations; corrections become `HUMAN_VALIDATED` trusted context and bump the version. | Edited proposal persists with `source=HUMAN_VALIDATED`, is excluded from re-proposal, and outranks LLM proposals in retrieval |
| FR-011 | **Context versioning.** Versions are monotonic per scope, immutable once ACTIVE, linked by `supersedes`, and carry `schema_hash` plus artifact `schema_version`. | History endpoint returns ordered versions; rebuilding produces version+1; older versions remain readable |
| FR-012 | **Context retrieval.** Retrieve relevant artifacts by tenant/connection/table (exact) and by graph traversal (related concepts, metrics, join paths) within a bounded expansion; never return the whole store/graph. | Retrieval for a question returns only tables/columns/metrics matching the question's entities; a hostile "select everything" query still returns bounded slices |
| FR-013 | **Context composition and compilation.** Merge persistent + runtime context under a token budget with ordered degradation; emit a deterministic `ContextPackage` for `sql.planner`; governance and granularity are never dropped. | Same inputs produce byte-identical packages; over-budget packages drop sections in the documented order and record them in `budget.dropped_sections`; if governance/grain cannot be included the package is `INSUFFICIENT` |
| FR-014 | **Context invalidation.** Invalidate on schema change (`schema_hash` mismatch), entitlement/permission change, manual request, or staleness policy; invalidation marks `STALE` and queues rebuild. | Simulated column addition flips the record to `STALE` and reports the cause; no request is served stale governance |
| FR-015 | **Context rebuild.** Rebuild is a staged, resumable, idempotent job with per-stage status, retries, cancellation, and partial-failure tolerance. | Killing a job mid-ENRICHING and resuming skips completed stages; re-running a completed build produces a new version without duplicate graph nodes |
| FR-016 | **Context observability.** Emit the documented `context_*` audit events and metrics through existing observability infrastructure. | `/metrics` exposes context counters/histograms; `/audit` shows build and validation events with actor and decision |
| FR-017 | **Graph backend replaceability.** The context domain compiles and runs with no graph backend installed; `GraphRepository` contract tests apply to every backend. | Core package imports without Neo4j driver; contract suite passes against the Neo4j adapter and a fake in-memory adapter |
| FR-018 | **Security and tenant isolation.** No credentials or raw sensitive values in any artifact; tenant filtering at the service layer; trust levels on all content; Cypher never assembled from user/model text. | Security tests: cross-tenant retrieval returns nothing; sensitive-patterned values never appear in artifacts/logs; injected instructions in comments/descriptions remain `UNTRUSTED` data |
| FR-019 | **Planner integration.** The planner consumes a compiled `ContextPackage` through the existing pipeline while preserving plan validation, guardrails, audit, and behavior when the Context Layer is unavailable. | With context enabled and disabled, existing planner tests pass; compiled context replaces the ad-hoc schema/metric assembly only |
| FR-020 | **Failure degradation.** Context Layer failures never break question answering; the system degrades to current behavior or clarifies when quality is `INSUFFICIENT`. | Graph down, store down, or LLM down each produce defined degradation paths (see §5); `/ask` continues to function |

## 4. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-001 | **Scalability.** Build cost is bounded per scope (table caps, profiling query caps via provider `max_result_rows`, no unbounded scans); retrieval and compilation are O(relevant context), not O(catalog) |
| NFR-002 | **Reliability.** Stages are checkpointed; jobs are idempotent per stage; registry state is durable; graph projection is reproducible from the registry |
| NFR-003 | **Security.** Application-layer tenant isolation; trust levels; secret scanning on artifact text; audit of build/validate/invalidate actions; fail-closed on unknown sensitivity |
| NFR-004 | **Observability.** Structured events and metrics per §FR-016; tenant identifiers excluded from metric labels; build and retrieval latencies measurable end-to-end |
| NFR-005 | **Multi-tenancy.** Every artifact, record, and graph node carries `org_id`/`project_id`; OSS default is a single implicit tenant; physical isolation is an Enterprise concern |
| NFR-006 | **Extensibility.** New artifact kinds and graph node/relationship types are additive with `schema_version` bumps; storage backends are swappable behind contracts |
| NFR-007 | **Performance.** Retrieval + composition + compilation target < 100 ms locally for typical scopes; build runs off the request path and never blocks connection creation |
| NFR-008 | **Availability.** No mandatory new service for OSS defaults (SQLite registry/store); the graph backend is optional; context features report unavailable rather than failing requests |
| NFR-009 | **Portability.** PostgreSQL → SQLite and Neo4j → alternatives are adapter-level changes; the domain model contains no vendor types; core installs with zero required dependencies |
| NFR-010 | **Testability.** Deterministic services are unit-testable without a database; graph adapters pass one shared contract suite; end-to-end scenario exercised in integration tests |

## 5. Failure modes

| Failure | Detection | Response |
|---|---|---|
| Schema introspection failure | Build stage error / provider exception | Stage `FAILED` with retry; previous ACTIVE version retained; API reports status and reason |
| Profiling failure (partial) | Per-column exception or timeout | Column skipped; `quality.profiling_coverage` reduced; job continues; warning recorded |
| Profiling failure (scope-wide, e.g. DB down) | Connect/introspection error | Build fails retryably; no partial version published; existing context remains ACTIVE with freshness warning |
| LLM unavailable / rate-limited | `ModelProviderError` | Deterministic artifacts publish; enrichment deferred (`validation=PENDING`, `warnings`); no LLM-derived content is trusted |
| Graph backend unavailable | `GraphRepository.health_check()` false / adapter exception | Context state `DEGRADED`; registry/store unaffected; graph-derived retrieval returns empty and is recorded in package `degraded` |
| Validation timeout (human) | Age beyond validation policy | Record stays `PENDING_VALIDATION`; proposals remain untrusted; agents may proceed with deterministic context only |
| Stale context served | `schema_hash` mismatch at retrieval | Rebuild queued; stale package served **only** with freshness warning; governance never stale |
| Partial build resumed incorrectly | Stage checkpoint/idempotency check | Re-running stage is safe (idempotent); duplicate graph nodes prevented by stable node keys |
| Graph inconsistency | Contract test / reconciliation check comparing registry vs graph counts | Rebuild graph projection from registry (registry is source of truth); alert metric incremented |
| Permission changes mid-session | `permission_version` mismatch | Affected caches invalidated; governance re-fetched; requests fail closed if authorization unavailable |
| Quality insufficient for safe planning | `QualityReport.state == INSUFFICIENT` | Compiler marks package insufficient; planner returns clarification instead of guessing (Principle 14) |
| Prompt injection via metadata | Input guardrail signatures / trust-level audit | Content retained as data with `UNTRUSTED` trust; instruction separation; audit event recorded |

## 6. Traceability

Every FR maps to milestones in [README.md](README.md): FR-001→M4, FR-003→M4, FR-004→M5,
FR-005–FR-008→M5, FR-009→M7, FR-010→M9, FR-011→M8, FR-012–FR-013→M10, FR-014–FR-015→M8,
FR-016→M12, FR-017→M6, FR-018→M12, FR-019→M11, FR-020→M12.
