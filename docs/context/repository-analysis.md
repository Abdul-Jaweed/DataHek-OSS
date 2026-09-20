# Context Layer — Repository Analysis

**Status:** Milestone 1 deliverable — proposed for review
**Scope:** Where the Context Layer integrates into DataHek OSS, what it must reuse, what it must
not duplicate, and where its boundaries should sit.

This analysis is grounded in the current `datahek-core` v0.2.0 codebase
(`src/datahek/`, 496 tests). It precedes the Context Layer research document and architecture.

---

## 1. Current architecture

DataHek OSS is a read-only conversational data engine composed of four layers plus four surfaces:

| Layer | Package | Responsibility |
|---|---|---|
| Kernel | `src/datahek/kernel/` | Primitives: `RequestContext` (tenant-aware), DI `Container`, `ExtensionRegistry`, `ErrorCode`, capabilities, entitlements, IDs, config |
| Contracts | `src/datahek/contracts/` | 24 `Protocol` interfaces + frozen-dataclass DTOs — the Enterprise extension boundary |
| Engine | `src/datahek/engine/` | The guarded pipeline: `SchemaService` → `Planner` (LLM → LogicalPlan) → `validate_plan` → `GuardrailPipeline` → `Engine` (execute) → masking → `Reasoner` → `Verifier`; plus `MultiStepAnalyst`, `SkillRegistry`, `FollowUpSuggester` |
| Defaults | `src/datahek/defaults/` | OSS implementations named by storage/locality (`Local*`, `Sqlite*`, `Postgres*`, `Env*`, `Jsonl*`, `Redis*`, `Infisical*`), composed in `defaults/container.py` |
| Connectors | `src/datahek/connectors/` | `ClickHouseProvider`, `PostgresProvider`, `MySQLProvider`, `SQLiteProvider`, `DuckDBProvider` implementing `DataProvider` |

Surfaces: REST API (`api/app.py`), CLI (`cli.py`), MCP server (`mcp_server.py`, 7 tools),
React web UI (`apps/web/`). Surfaces share one guarded pipeline and one normalized
`RequestContext` (`source` ∈ api/cli/ui/mcp/sdk/worker).

Key architectural rules the Context Layer must respect:

- **OSS is complete without Enterprise.** Extension happens through contracts + DI overrides, never
  edition checks; capabilities come from `kernel/capabilities.py`.
- **Read-only by construction.** Write plans are structurally impossible; providers enforce
  physical read-only.
- **`typing.Protocol` + frozen dataclasses** for contracts and DTOs. Pydantic is used only at the
  API boundary (`api` extra). Core has **zero required dependencies** — every backend is an
  optional extra.
- **Tenant-aware but single-tenant by default.** `RequestContext` carries
  `organization_id`/`workspace_id`/`project_id`; stores filter by org/project.

## 2. Existing components relevant to context

These already provide parts of what a Context Layer needs. The Context Layer must integrate with
them, not replace them.

| Concern | Existing component | What it provides | Context Layer relationship |
|---|---|---|---|
| Schema discovery | `engine/schema.py` — `SchemaService`, `SchemaCatalog`, `TableMeta`, `ColumnMeta`, TTL cache | Tables, columns, types, row counts; `tables()`, `columns()`, `column_types()` helpers | **Reuse** as the introspection source. Context Store persists a *versioned snapshot* of this; `SchemaService` remains the live cache |
| Semantic layer | `contracts/semantics.py` — `Metric`, `SemanticStore`; `defaults/semantics.py`/`semantics_pg.py`; `GET/POST/PUT/DELETE /semantics` | Named metric definitions (aggregate/column/filter on a table) | **Reuse and extend.** Metrics are a Context artifact (`SemanticsContext`). Do not create a second metric registry |
| Planner context assembly | `engine/planner.py` — `build_schema_summary`, `_format_metrics`, `_format_history`, skill prompt, prompt templates | Today's *de facto* context compiler: schema + metrics + skills + history + custom prompt → single LLM request | **Generalize.** The Context Compiler formalizes this; the planner becomes a consumer of a compiled Context Package |
| Skills | `engine/skills.py` — `Skill`, `SkillRegistry.match(question, catalog)`, `build_skill_prompt` | Keyword + precondition-gated domain guidance | **Reuse** as `CapabilityContext`. Skills are versioned capabilities, not context storage |
| Conversation state | `contracts/misc.py` — `ConversationStore`; SQLite/PG stores; history formatting | Recent turns for planner context | **Reuse.** Conversation context is runtime context, read from the existing store |
| Guardrails | `engine/guardrails.py` — `GuardrailPipeline`, typed decisions (`ALLOW/DENY/REDACT/MASK/REQUIRE_APPROVAL/RATE_LIMIT`), stages input/plan/sql/output | Injection detection, read-only enforcement, rate limits, policy | **Extend with a context trust boundary.** Context artifacts are untrusted-adjacent data; they must pass through the existing input guardrail path before reaching prompts |
| Policy | `defaults/policy.py` — `LocalPolicyEngine`; `contracts/policy.py` | Table allowlists, approval gating | **Reuse.** Context must never bypass policy; governance context is *descriptive*, enforcement stays in policy + guardrails |
| Audit | `contracts/audit.py` — `AuditSink`, `AuditEvent`; `defaults/audit.py` JSONL; `/audit` search | Decision records | **Reuse**: `context.*` event types (`context_build_started`, `context_validated`, …) |
| Observability | `defaults/metrics.py` Prometheus text, JSON logs, `GET /metrics` | Counters/observations, structured logs | **Reuse**: add `context_*` metrics via `LocalMetrics` |
| Persistence | `defaults/pg.py` — `PgMetadata` with **versioned migrations** (`schema_migrations`, advisory lock), SQLite fallback | Durable metadata store | **Extend**: Context Registry tables become new numbered migrations |
| DI + extension | `kernel/di.py` `Container` (+`override`), `kernel/registry.py` `ExtensionRegistry` | OSS composition; Enterprise attach points | **Use**: Context services register in `build_default_container`; Enterprise overrides through `Container.override` |
| Tenancy | `kernel/context.py` `RequestContext`, `TenantScope`; `contracts/tenancy.py` `TenantContext`; `defaults/tenancy.py` `SingleTenantContext` | Tenant-aware request model | **Reuse**: context artifacts carry `org_id`/`project_id`; enforcement at the application layer |
| Entitlements | `kernel/entitlements.py` `EntitlementProvider` (+`EntitlementService` contract) | Static OSS limits, replaceable provider | **Use** for context-layer limits (e.g., max profiled tables) as defaults, not hard restrictions |
| Background work | `defaults/scheduler.py` `LocalScheduler` (in-process, poll-based); `contracts/misc.py` `JobStore` (contract only, no implementation) | Schedule polling | **Pattern to follow** for `ContextBuildJob`; note `JobStore` is unimplemented — do not invent a second job abstraction until needed |
| Model access | `contracts/models.py` `ModelProvider`; `defaults/models.py` OpenAI-compatible | LLM completions | **Reuse** for semantic enrichment; proposals are `pending_validation`, never authoritative |
| MCP | `mcp_server.py`, 7 tools, per-tool scopes | External agent access | Future: context tools (`context.get`, `context.status`) — not V1 |

## 3. Integration points

1. **Planner input** (`engine/planner.py`): the compiled Context Package replaces the ad-hoc
   assembly (`build_schema_summary` + `_format_metrics` + skills + history). The planner keeps its
   retry/feedback loop and plan validation unchanged.
2. **`SemanticStore`**: metrics/dimensions/identifiers produced by enrichment and validated by
   humans are stored through the existing store (extended, not duplicated).
3. **`SchemaService`**: introspection reuse for build jobs; `ContextStore` snapshots are versioned
   copies with a `schema_hash`.
4. **`PgMetadata`**: registry/artifact/job tables as versioned migrations; SQLite equivalents for
   the zero-dependency default.
5. **`RequestContext`**: every registry/store/retriever call takes `ctx` and filters by
   org/project — no context API that ignores tenancy.
6. **Guardrails**: context text destined for a prompt passes input-guardrail checks; provenance and
   trust levels are attached to every artifact.
7. **API surface** (`api/app.py`): new `/connections/{id}/context*` and `/contexts/*` routes
   following existing patterns (error codes via `DatahekError`, status map, auth dependency).
8. **Compose/deployment**: Neo4j becomes an **optional** service/profile; the OSS stack must still
   run without it (graph features degrade; registry remains in PostgreSQL/SQLite).

## 4. Missing abstractions (to be built)

- **Context domain model**: ContextPackage, ContextArtifact variants (Schema/Profile/Taxonomy/
  Ontology/Topology/Granularity/Governance/Capability), provenance, quality, freshness — none of
  this exists today beyond the raw `SchemaCatalog` and `Metric`.
- **Context Registry**: identity, versions, lifecycle states, `schema_hash`, invalidation.
- **Context Store**: durable artifact persistence (PostgreSQL + SQLite default).
- **Schema Profiler**: cardinality/null ratios/min/max/distribution, candidate identifiers,
  dimensions, measures, temporal fields — deterministically computed, privacy-aware.
- **Taxonomy / Ontology / Topology / Granularity services**: semantic representations over the
  schema graph.
- **Graph abstraction**: `GraphRepository` protocol + `Neo4jGraphRepository` adapter + contract
  test suite.
- **Schema Knowledge Graph builder**: canonical node/relationship vocabulary, tenant-scoped.
- **Human validation**: pending → validated workflow with provenance transitions
  (`LLM` → `HUMAN_VALIDATED`), corrections as first-class trusted context.
- **Context Retrieval / Composition / Compilation**: relevance selection and token budgeting for
  the LLM, replacing "send everything".
- **Context build jobs**: asynchronous, staged, retryable, observable.

## 5. Potential conflicts and risks

| # | Conflict | Assessment | Recommendation |
|---|---|---|---|
| 1 | **Semantic layer duplication** — `Metric`/`SemanticStore` already exist and the planner consumes them | High risk of two competing metric systems | Context Layer *extends* the semantic layer: metrics become a `SemanticsContext` artifact whose validated definitions live in the existing store |
| 2 | **Planner prompt assembly** already exists ad hoc | The Context Compiler could fork prompt-building logic | Planner keeps prompt *formatting*; it consumes a compiled structured package. One assembly path only |
| 3 | **Pydantic vs dataclasses** — brief asks for Pydantic contracts; repo convention is frozen dataclasses in core (zero required deps) | Convention conflict | Use dataclasses for domain contracts/DTOs; Pydantic only at the API boundary (existing pattern). Flagged for decision |
| 4 | **Package layout** — brief proposes `src/datahek/context/` with everything inside; repo convention separates contracts / engine / defaults | Layout conflict | Split per convention: `contracts/context*.py` (Protocols+DTOs), `context/` (domain services + graph abstraction), `defaults/context_*.py` (stores + Neo4j adapter) |
| 5 | **Neo4j licensing** — Community Edition is GPLv3; it runs as a separate server, so it does not infect Apache-2.0 Python code, but it is an optional component | Moderate: document clearly | Neo4j is an optional extra (`[graph]`) and optional compose profile; graph features degrade gracefully. The graph abstraction keeps alternatives viable (FalkorDB is SSPLv1 — the SSPL "service" trigger must be noted; PostgreSQL AGE/recursive CTEs remain the license-safe fallback) |
| 6 | **Multi-tenancy** — OSS is single-tenant; brief requires tenant-aware context | Pattern already established | Every artifact carries `org_id`/`project_id`; application-layer filtering; physical isolation is a later Enterprise concern |
| 7 | **`docs/` is gitignored** except `docs/adr/` (deliberate standardization decision) | Context docs would be invisible to contributors | Track `docs/context/` like `docs/adr/` (gitignore negation) |
| 8 | **Job infrastructure absent** — `JobStore` is contract-only; scheduler is in-process | Building a full job system now expands scope | V1: in-process build task following `LocalScheduler` patterns + durable registry status. `JobStore` implementation is a later milestone |
| 9 | **Zero-dependency core** — Neo4j driver / graph libs must stay optional | Constraint | `[graph]` extra; import guarded with `try/except ImportError` exactly like `pg.py`/`redis_llm.py` |
| 10 | **Prompt injection via metadata** — DB comments/names, LLM proposals, tool output | Security-critical | Context trust levels (`SYSTEM`/`DATABASE`/`LLM`/`HUMAN_VALIDATED`), instruction/data separation, existing input guardrails on any context text entering prompts |

## 6. Recommended Context Layer boundaries

```
src/datahek/
├── contracts/
│   └── context.py                  # GraphRepository, ContextRegistry, ContextStore,
│                                   # ContextBuilder/Retriever/Composer protocols
│                                   # + DTOs: ContextPackage, artifacts, provenance,
│                                   # lifecycle states, quality, freshness
├── context/                        # domain services (LLM-free where deterministic)
│   ├── __init__.py
│   ├── models.py                   # internal model helpers (versioned artifacts)
│   ├── lifecycle.py                # state machine + transitions
│   ├── provenance.py               # source/confidence/validation rules
│   ├── quality.py                  # quality dimensions (per-dimension, not one score)
│   ├── freshness.py                # per-artifact freshness policy
│   ├── hashing.py                  # canonical schema hashing (SHA-256)
│   ├── profiler.py                 # deterministic, privacy-aware profiling
│   ├── enrichment.py               # LLM proposals (pending_validation)
│   ├── taxonomy.py                 # Domain→Subdomain→Entity→Attribute
│   ├── ontology.py                 # entities/concepts/relationships
│   ├── topology.py                 # FK/join paths/cardinality/confidence
│   ├── granularity.py              # table/entity/metric/temporal grain
│   ├── registry.py                 # ContextRegistry (metadata/lifecycle/version)
│   ├── retriever.py                # exact → graph → (future semantic)
│   ├── composer.py                 # budget-aware composition
│   ├── compiler.py                 # structured package → agent context
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── protocol.py             # engine-independent graph contract
│   │   ├── models.py               # GraphNode/GraphRelationship/GraphPath
│   │   └── neo4j.py                # Neo4jGraphRepository (Cypher stays here)
│   └── jobs/
│       └── build_context.py        # staged ContextBuildJob
├── defaults/
│   ├── context_store.py            # SQLite ContextStore
│   ├── context_store_pg.py         # PostgreSQL ContextStore (migrations)
│   └── context_bootstrap.py        # container wiring for context services
└── api/ (routes)
```

Boundary rules:

- `context/` never imports Neo4j or Cypher; it depends on `contracts/context.py`'s
  `GraphRepository`.
- `defaults/context_*` and `context/graph/neo4j.py` are the only places that know about storage
  engines; wiring happens in `defaults/container.py` (OSS) and `Container.override` (Enterprise).
- Every public context service takes `RequestContext` as its first argument and filters by tenant.
- Nothing in the Context Layer executes SQL against user databases except through the existing
  `Engine`/`DataProvider` path (profiling uses `DataProvider.compile_and_execute` with generated
  read-only plans or provider helpers — never raw user SQL assembled from context).

## 7. Open questions for the M1 review gate

1. **Layout**: adopt the convention-split recommendation (§6) or the brief's single `context/`
   tree with contracts inside?
2. **Contracts type system**: dataclasses in core + Pydantic at API (recommended, matches repo and
   zero-dependency rule) vs Pydantic everywhere (brief's wording)?
3. **Docs tracking**: track `docs/context/` in git like `docs/adr/` (recommended)?
4. **Neo4j in compose**: optional profile (`docker compose --profile graph up neo4j`) with the
   default stack unchanged (recommended)?
5. **V1 profiling depth**: deterministic aggregates only (counts, null %, distinct, min/max, small
   samples of distributions) with strict value exposure rules — confirm no raw value sampling into
   prompts even when profiled?
