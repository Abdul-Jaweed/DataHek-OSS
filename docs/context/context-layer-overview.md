# Context Layer — How It Works (Overview & Sequencing)

Consolidated explanation of the DataHek Context Layer: what it is, how it is built, how it runs
at question time, and every sequencing guarantee in between. Companion deck:
[`context-layer-deck.html`](context-layer-deck.html). Deep dives live in the per-module docs
linked throughout.

---

## 1. What it is

The Context Layer is a first-class subsystem that produces the **minimum relevant, trustworthy,
governed, versioned, task-appropriate information** an agent needs to answer correctly — as
structured artifacts, not prose. A system prompt is one consumer of context, not the context
itself.

```
Persistent Context → Retrieval → Selection → Composition → Compilation → Context Package → Agent → LLM
```

Three principles drive the design:

1. **Deterministic by default.** Only one stage (semantic enrichment) uses an LLM; everything
   else is rule-based, reproducible, and testable without a model.
2. **Fail closed.** Unknown semantics clarify; unsafe values deny; unverifiable plans are
   rejected. The system never guesses on the user's behalf.
3. **Bounded always.** Retrieval caps tables/columns, composition caps tokens, the graph reads
   are depth-bounded — a hostile "select everything" question still returns small slices.

## 2. Architecture at a glance

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                     Context Layer                       │
                    │                                                         │
  connection ─────► │  snapshot ─► profiler ─► topology ─► granularity        │
  (credentials      │      │           │            │            │             │
   never enter      │      ▼           ▼            ▼            ▼             │
   artifacts)       │  taxonomy ◄── profiles     join graph   grain rules      │
                    │      │                                                  │
                    │      ▼                                                  │
                    │  enrichment (LLM, optional, PENDING)                    │
                    │      │                                                  │
                    │      ▼                                                  │
                    │  Schema Knowledge Graph (Neo4j | in-memory)             │
                    │      │                                                  │
                    │      ▼                                                  │
                    │  quality + freshness ─► registry (versioned, immutable) │
                    └───────────────┬─────────────────────────────────────────┘
                                    │  active record (per tenant + connection)
                                    ▼
             question ─► retriever ─► composer ─► compiler ─► ContextPackage
                                                                │
                                                                ▼
                                                   planner (sql.planner purpose)
```

Key components and their files:

| Component | File | Role |
|---|---|---|
| Snapshot | `context/snapshot.py` | Catalog → canonical `SchemaContext` + SHA-256 schema hash |
| Profiler | `context/profiler.py` | Batched aggregates: null ratio, distinct, min/max/avg, roles |
| Topology | `context/topology.py` | FK edges, `<entity>_id` inference, bounded join paths |
| Granularity | `context/granularity.py` | "1 row of X means …" grain statements |
| Taxonomy | `context/taxonomy.py` | Domain → Subdomain → Category classification |
| Enrichment | `context/enrichment.py` | The only LLM stage: ontology proposals (PENDING) |
| Graph builder | `context/graph/builder.py` | Projects everything into the Schema KG |
| Registry | `context/registry.py` | Publish / supersede / invalidate through the lifecycle |
| Retriever | `context/retriever.py` | Deterministic question-token selection |
| Composer | `context/composer.py` | Token budget + ordered degradation |
| Compiler | `context/compiler.py` | Deterministic `ContextPackage` for the planner |

## 3. Artifacts (what is stored)

Every artifact carries an `ArtifactEnvelope`: kind, schema version, provenance
(`database | system | llm | human_validated`), trust (`structural | system | validated |
proposed`), validation status, confidence, timestamp.

| Artifact | Contents | Provenance |
|---|---|---|
| Schema | Tables, columns, types, PK/FK, indexes, nullability | Database |
| Profile | Per-column null ratio, distinct count, uniqueness, min/max/avg, role candidates | Database |
| Topology | Join edges (FK + inferred), cardinality, fanout risk, bounded join paths | Database / inferred |
| Granularity | Table grain statements, metric-grain caveats | System |
| Taxonomy | Role-based hierarchy (Dimension/Measure/Identifier/Temporal/…) | System |
| Ontology | Concepts, synonyms, controlled relationships | LLM (PENDING) |
| Governance | Sensitive/restricted columns, allowed operations, permission version | System |
| Quality | Six coverage dimensions + state (`sufficient | marginal | insufficient`) | System |
| Freshness | Age, schema-hash match, permission-version match, refresh due | System |

Sensitive columns are **counts-only**: no raw values, no samples, ever.

## 4. Build sequencing (persistent context)

The build job (`context/jobs/build_context.py`) runs nine ordered stages, each retried once,
each independently degraded:

```
INTROSPECT ─► PROFILE ─► TOPOLOGY ─► GRANULARITY ─► TAXONOMY ─► ENRICH ─► GRAPH_BUILD ─► QUALITY ─► PUBLISH
   │            │           │            │              │           │            │            │          │
 catalog      stats       joins        grains        classes      concepts     KG nodes     scores    version
```

Sequencing rules:

1. **Order is fixed** — later stages depend on earlier artifacts (topology needs schema,
   taxonomy needs profiles, enrichment needs taxonomy, graph needs everything).
2. **Retries** — each stage retries once on transient failure.
3. **Degradation** — a failed stage yields `degraded` with a warning; the build continues and
   publishes a lower-quality record rather than failing wholesale.
4. **Enrichment is opt-in** — spends model tokens, so `enrichment=false` is the default for
   automated builds; proposals arrive as `PENDING` and never become authoritative.
5. **Skip-if-current** — a build whose schema hash matches the active record is skipped.
6. **Idempotent graph** — rebuilds MERGE by stable ids and prune stale nodes per connection.
7. **Publish is last and atomic** — a new version supersedes the previous one; older versions
   remain readable forever.

Live reference (InsForge, 40 columns / 730k rows): total ~29 s, with `PROFILE` ≈ 27 s
(distinct counts dominate; exact counts kept).

## 5. Lifecycle and versioning

```
BUILDING ─► ACTIVE ─► SUPERSEDED
                │  └─► STALE ─► (rebuild) ─► ACTIVE (v+1)
                └─► INVALIDATED
```

- Versions are monotonic **per `(org, connection, scope)`**; ACTIVE versions are immutable.
- `supersedes` links versions; `previous_version` allows history walks.
- Invalidation triggers: schema-hash mismatch, permission-version change, manual request,
  staleness policy. Invalidation marks `STALE`; retrieval surfaces `stale=true` and never serves
  stale governance.

## 6. Runtime sequencing (question → answer)

Every `/ask` compiles context **before** planning:

```
POST /ask
  │
  ├─ 1. Input guardrail          (injection / denied patterns — before any model call)
  │
  ├─ 2. Retrieve                 active record → tokens → bounded selection
  │      └─ no record / store down ──────────────────────────────► live catalog fallback
  │
  ├─ 3. Compose                  budget 4000 → ordered degradation
  │      └─ mandatory sections don't fit ──► insufficient_reason="budget"
  │
  ├─ 4. Compile                  deterministic ContextPackage, trust floor, semantics summary
  │      └─ INSUFFICIENT ────────────────────────────────────────► clarification (fail closed)
  │
  ├─ 5. Planner                  package schema + grain + joins + restricted cols + metrics
  │      └─ prompt → model → parse → normalize → validate → retry with feedback
  │
  ├─ 6. Engine                   guardrails → policy (+RLS FILTER) → approval → execute
  │
  └─ 7. Assembly                 checkpoint(executed plan) → explain ∥ verify ∥ suggest → response
```

Exact order guarantees:

| # | Guarantee | Why it matters |
|---|---|---|
| 1 | Retrieval happens before any model call | deterministic, cheap (~36 ms), auditable |
| 2 | Missing/invalid context degrades to live catalog | the Context Layer never breaks `/ask` |
| 3 | `INSUFFICIENT` packages clarify instead of guessing | no answers on unverified foundations |
| 4 | Policy/RLS run **after** planning, in the engine | context informs the plan; guardrails enforce |
| 5 | Checkpoints store the **executed** plan (post-RLS) | re-execution and audit see real SQL |
| 6 | Explain/verify/suggest run concurrently | up to two model latencies removed |

## 7. Retrieval

`ContextRetrieverService.retrieve(ctx, connection_id, question, current_schema_hash)`:

1. Read the ACTIVE record (tenant-scoped) and its artifacts **in parallel**.
2. Tokenize the question: lowercase, split snake_case identifiers (`error_category` →
   `error`, `category`), drop stopwords.
3. Score tables: name match ×3, any column match +2, metric/ontology/taxonomy boosts; pull in
   one-hop join neighbours.
4. Caps: **8 tables, 40 columns**; no matches at all → schema-order floor.
5. Filter slices: profiles, grain, taxonomy, ontology to selected tables; topology to edges
   **between** selected tables; metrics by token overlap.
6. Governance is always attached in full.
7. Return `stale=true` when `current_schema_hash` differs — caller queues a rebuild.

## 8. Composition

`BudgetContextComposer.compose(..., budget_tokens=4000)`:

- Cost model: `len(str(section)) // 4` — deterministic, monotonic.
- **Mandatory**: schema, governance, granularity. If they alone exceed the budget →
  `insufficient_reason="budget"`.
- **Optional drop order**: `profiles → taxonomy → topology → ontology → metrics`.
- Metrics get relevance pruning before being dropped wholesale.

## 9. Compilation

`PackageContextCompiler.compile(...)` — same inputs produce byte-identical packages:

- **Semantics summary**: dimensions/identifiers/temporal from taxonomy categories; profile roles
  as fallback; metrics carried through.
- **Trust floor**: minimum effective trust of included content (an included LLM ontology lowers
  the package to `PROPOSED`).
- **Governance**: composed governance or a synthesized SYSTEM block (`SELECT` only).
- **Degradation**: dropped sections recorded in `budget.dropped_sections` and `degraded`.
- **Fail closed**: insufficient composition overrides `quality.state=INSUFFICIENT` with the reason.

## 10. Planner integration and degradation matrix

With a package, the planner renders schema + grain + joins + restricted columns + metrics and
**skips the live catalog fetch**. Without one, the existing path runs unchanged.

| Failure | Behavior |
|---|---|
| No active record | Live-catalog planning; `/ask` unaffected |
| Store/retriever down | Log warning, live-catalog fallback |
| Package INSUFFICIENT | Clarification (no guessing) |
| Stale context | Returned with `stale=true`; planner still works |
| Preview store failure | `CONTEXT_UNAVAILABLE` (503) with reason |

## 11. Human validation loop

`context/validation.py`:

1. Build produces `PENDING` items (ontology concepts/relationships, taxonomy nodes, grains).
2. `GET /connections/{id}/context/pending` lists them with labels, provenance, confidence.
3. `POST …/context/validate` applies `approve | edit | reject` (whitelisted edits) and publishes
   a **new version** with `HUMAN_VALIDATED` provenance.
4. Validated items become fixed priors for the next enrichment run — humans are never asked the
   same question twice.

## 12. Schema Knowledge Graph

`context/graph/*` projects schema, profiles, topology, grain, taxonomy, metrics, and ontology
into a property graph with stable ids, vocabulary-only edges, version/provenance stamps, and
idempotent rebuilds. Neo4j is optional (`[graph]` extra + compose profile); the in-memory
adapter passes the same contract suite, and every read is tenant-scoped and depth-bounded.

## 13. Security and tenancy

- Credentials never enter artifacts (verified by a full build with a password-bearing connection).
- Sensitive columns contribute counts only; taxonomy excludes them.
- Every registry/store read is scoped by `org_id` at the storage layer; cross-tenant
  retrieval/validation returns nothing.
- LLM content is `PROPOSED`/`PENDING`, can never raise a package's trust floor, and reaches
  prompts only as data — never the system prompt.
- Cypher is confined to the Neo4j adapter; no model text is interpolated into queries.

## 14. Observability

Metrics at the API boundary: `datahek_context_builds_total`, `…_build_duration_seconds`,
`…_retrievals_total{hit|miss|insufficient|error}`, `…_retrieval_duration_seconds`,
`…_tokens`, `…_insufficient_total`, `…_validations_total`. Audit events: `context.build`,
`context.validate`. No tenant ids in metric labels; no artifact contents in audit payloads.

## 15. Milestones and evidence

| Milestone | Deliverable | State |
|---|---|---|
| M1 | Repository analysis + research | Complete |
| M2 | Architecture, context model, SRD, ADRs | Complete |
| M3 | Domain model + contracts | Complete |
| M4 | Schema discovery + profiling | Complete |
| M5 | Taxonomy, ontology, topology, granularity | Complete |
| M6 | Graph abstraction + Neo4j adapter | Complete |
| M7 | Schema Knowledge Graph builder | Complete |
| M8 | Registry, persistence, versioning | Complete |
| M9 | Human semantic validation | Complete |
| M10 | Retrieval, composer, compiler | Complete |
| M11 | SQL agent integration + REST surface | Complete |
| M12 | Testing, observability, security hardening | Complete |

Live evidence: InsForge `unified_events` (730,962 rows / 40 columns) — build ~29 s, retrieval
~36 ms, composition/compilation < 0.1 ms, 215-query E2E campaign **215/215 correct-or-safe**,
full test suite **733 tests OK**.

## 16. Reproduce

```bash
K:/DataHek/.venv/Scripts/python.exe -m unittest discover tests
K:/DataHek/.venv/Scripts/python.exe scripts/e2e/bench_components.py
K:/DataHek/.venv/Scripts/python.exe scripts/e2e/api_contract_check.py
K:/DataHek/.venv/Scripts/python.exe scripts/e2e/run_parallel.py --workers 3
```

REST surface: `GET/POST /connections/{id}/context[/build|/versions|/pending|/validate|/preview]`,
`GET /contexts/{id}`. Full API reference: [`api.md`](api.md). Per-module specifications:
[README](README.md).
