# Context Layer — Research

**Status:** Milestone 1 deliverable — proposed for review
**Purpose:** Establish shared vocabulary and technical grounding for the DataHek Context Layer.
Every term below gets a **DataHek-specific definition** — no imported terminology without a
concrete meaning in this system.

---

## 1. Context engineering (what we mean in DataHek)

| Concept | Generic meaning | DataHek definition |
|---|---|---|
| Context | Information given to a model for a task | The **minimum relevant, trustworthy, governed, versioned, task-appropriate information** required by an agent to perform a task correctly — as structured artifacts, not prose |
| Context window | Model token limit | A hard budget the Context Compiler must respect; the reason retrieval/selection exists at all |
| Context selection | Choosing what to include | Deterministic relevance: tables matching the question's entities, metrics matching business terms, topology needed for joins, grain needed for correct aggregation |
| Context compression | Shrinking context to fit | Ordered degradation: drop provenance detail → drop unmapped columns → drop profile statistics → drop semantic descriptions. Never drop governance or grain |
| Context assembly | Building the final input | The `ContextComposer` (merge persistent + runtime) and `ContextCompiler` (emit the deterministic structured package the planner consumes) |
| Context routing | Directing context by task | V1: one target (`sql.planner`). The compiler takes a `purpose` parameter so verifier/explainer consumers can be added without redesign |
| Structured context | Machine-readable context | The `ContextPackage` — typed, versioned, with field-level provenance; never a free-text blob |
| Dynamic context | Per-request context | Runtime Context: question, intent, selected tables/columns/metrics/joins, conversation state, applicable policy decisions |
| Persistent context | Reusable context | Schema, profile, taxonomy, ontology, topology, granularity, governance, validated semantics, and the Schema KG — built once per schema version, invalidated by schema change |
| Task context | What the task needs | The compiler's purpose-specific slice (e.g., for a revenue question: `orders.amount`, `orders.created_at`, grain=order, metric=revenue) |
| Tool context | What tools exist | `CapabilityContext`: registered `DataProvider`s and their capabilities; MCP tool availability; not their full schemas |
| Runtime context | State during execution | Live state: streaming stage, approval id, engine limits. Not persisted by default |
| Semantic context | Meaning-level context | Validated metrics, dimensions, identifiers, temporal fields, entity concepts — the output of taxonomy/ontology/enrichment after human validation |
| Context caching | Reusing computed context | Cached by `(org, project, connection, artifact, version)`. Permission-sensitive context (governance) is cached only with the permission version in the key |
| Context provenance | Where context came from | `source` (`DATABASE` / `SYSTEM` / `LLM` / `USER` / `HUMAN_VALIDATED` / `INFERRED` / `IMPORTED`), `confidence`, `status` |
| Context freshness | Whether context is current | Per-artifact freshness policy (see §7): schema = event-driven invalidation, statistics = periodic, business semantics = long-lived, permissions = near-real-time, tools/skills = versioned |
| Context versioning | Which context generation | Monotonic `version` per `(connection, table)` scope, plus `schema_hash` for change detection; the registry is the source of truth |

**Core framing:** a system prompt is *one consumer* of context. In DataHek the compiled package is
consumed by the planner today, and is designed to be consumed by verifier, explainer, multi-step
analyst, and MCP tools later.

## 2. Agent context architecture (DataHek model)

**Context vs memory.** Memory is *state that persists across requests* (conversations, validated
semantics, user corrections). Context is *what a given call needs*. DataHek already separates
these: `ConversationStore` (memory) vs what the planner currently assembles (context).

**Short-term vs long-term.** Short-term = conversation window (existing `_format_history`,
bounded at ~2000 chars). Long-term = persistent context artifacts (schema semantics, validated
metrics, human corrections).

**Context contamination.** Untrusted text entering trusted zones — a table comment that says
"ignore previous instructions", a malicious string inside profile output, or LLM-generated
descriptions treated as facts. DataHek's defense: trust levels on artifacts, instruction/data
separation in prompt construction, and the existing input guardrail applied to any context text
that reaches a prompt.

**Context staleness.** The agent reasoning over a schema that changed. DataHek's defense:
`schema_hash` (canonical SHA-256 of the normalized schema), lifecycle states, and pre-request
freshness checks in retrieval.

**Agent context architecture — what DataHek will *not* build.** No peer-to-peer agent mesh, no
context-owning agent, no autonomous context curation. Agents reason; deterministic services
decide. The Context Layer is a **service subsystem**: build → registry → retrieve → compose →
compile, each a plain async service callable by any agent.

**Where each consumer gets context (target state):**

```
Planner        ← compiled package (schema slice, metrics, grain, topology, policy, skills)
Verifier       ← question + result + grain + metric definitions (checks aggregation correctness)
Explainer      ← result schema + column semantics + provenance (grounds its prose)
Analyst        ← persistent context for decomposition, runtime context per sub-question
MCP tools      ← capability-scoped compiled packages (never the whole graph)
```

## 3. Database semantic understanding

What DataHek can know about a database, in the order it can be known:

1. **Structural (deterministic, from catalog):** databases → schemas → tables → columns; types;
   nullability; defaults; primary keys; foreign keys; unique constraints; check constraints;
   indexes; comments (untrusted); row estimates.
2. **Statistical (deterministic, from profiling):** row count; null ratio; distinct count;
   min/max/avg (numeric & temporal); value length ranges (text); top-k frequency buckets for
   low-cardinality columns; uniqueness ratio.
3. **Role classification (deterministic + rules):** identifiers (unique, non-null, joinable),
   measures (numeric, additive candidates), dimensions (low-cardinality categorical/temporal),
   temporal fields (date/timestamp with monotonic or range semantics).
4. **Semantic (LLM-proposed, human-validated):** what a table *means*, what a column *represents*,
   business names, metric candidates, grain statements.
5. **Business (human-authored):** metric definitions, dimensions, taxonomy placement, sensitive
   classifications — the only authoritative semantic layer.

**Identifier vs dimension vs measure.** A column that is unique and non-null is a candidate
identifier; a low-cardinality text column is a candidate dimension; additive numerics are measure
candidates. Candidates are *proposals* with confidence, never facts.

**Data grain** (critical for SQL correctness): the entity a table row represents.
`orders` (1 row = 1 order) vs `order_items` (1 row = 1 line item). DataHek's plan/aggregate model
makes grain errors classically destructive: `SUM(amount)` over item-grain rows double-counts an
order. Granularity context is therefore a **correctness input**, not documentation.

## 4. Taxonomy vs ontology (kept strictly separate)

**Taxonomy = classification hierarchy.** "What kind of thing is this?"
```
Commerce
└── Orders
    ├── Identifiers   (order_id, customer_id)
    ├── Measures      (amount)
    ├── Dimensions     (status)
    └── Temporal       (created_at)
```

**Ontology = concepts and their relationships.** "What things exist and how do they relate?"
```
Customer ──places──▶ Order ──contains──▶ Product
   Order ──has_amount──▶ Amount
   Order ──occurred_at──▶ CreatedAt
```

Rules:
- Taxonomy organizes *columns* (and tables) into a navigable hierarchy with a controlled category
  vocabulary (`Identifier`, `Measure`, `Dimension`, `Temporal`, `Categorical`, `Text`, `Boolean`,
  `Complex`).
- Ontology defines *entities/concepts* and typed relationships (`places`, `contains`,
  `belongs_to`, `has_amount`, `occurred_at`, `identifies`).
- Topology is **not** ontology: topology is structural connectivity (`orders.customer_id →
  customers.id`); ontology is meaning (`Customer places Order`). A join path can exist without an
  ontological relationship, and vice versa.
- Both are versioned artifacts with provenance; ontology relationships proposed by an LLM are
  `pending_validation` until a human confirms.

## 5. Topology (structural connectivity)

What topology represents in DataHek:

- **FK relationships** (from catalog constraints) — highest confidence.
- **Inferred join candidates** (name/type/cardinality heuristics: `x_id` matching a PK `x.id`,
  type families compatible, distinct counts comparable) — confidence-scored proposals.
- **Join paths** (shortest paths between two tables in the schema graph; max depth bounded).
- **Direction and cardinality** (1:1, 1:N, N:1, N:M) — estimated from uniqueness ratios and FK/PK
  status.
- **Joinability** — the practical question the planner asks: "can I join these two tables, on
  which columns, and with what expected fan-out?"

Topology is stored in the Schema Knowledge Graph (and mirrored as a `TopologyContext` artifact) so
retrieval can answer "what joins does this question need?" without re-deriving it.

## 6. Granularity (grain) model

Six grains DataHek tracks:

| Grain | Meaning | Example |
|---|---|---|
| Table grain | Entity per row for a table | `orders`: 1 row = 1 order |
| Entity grain | Entity a table *primarily* represents | `customers` table → Customer |
| Metric grain | Level at which a metric is valid | `revenue` valid at order grain; invalid (double-counts) at item grain without aggregation |
| Temporal grain | Native time resolution of a temporal column | `event_time` = event-level; `day_of_week` = derived |
| Aggregation grain | Level an aggregate output is reported at | daily counts vs monthly revenue |
| Dimensional grain | Dimension columns at which measures are additive | `amount` additive across `status`, not across `order_id` |

Grain statements are canonicalized as: `"1 row of <table> = 1 <entity> ['('<qualifier>')']"`.
Grain proposals come from heuristics + LLM, and must be human-confirmable (the canonical
acceptance scenario in the brief asks exactly this question).

## 7. Freshness policy (per artifact, not global TTL)

| Artifact | Trigger | Detection |
|---|---|---|
| Schema | Event-driven | `schema_hash` mismatch on request/build check |
| Profile (statistics) | Periodic (default: deferred until stale by age) | Age + row-count drift beyond threshold |
| Taxonomy | On schema or semantic change | Parent version change |
| Ontology | On human approval / semantic change | Version bump on validated changes |
| Topology | On schema change | FK/index hash change |
| Granularity | On profile drift or human correction | Version bump |
| Governance | Near-real-time | Permission/policy version in the retrieval path; never served stale to authorization decisions |
| Capabilities (skills/tools) | Versioned | Registry version comparison |
| Semantics (metrics) | Human-validated, long-lived | Version bump on edit; new candidates are proposals |

Staleness is *reported* (`freshness.age_s`, `freshness.state`) — consumers decide. The context
package includes freshness so the planner/agent can refuse or warn, per Principle 14 (fail closed
when quality is insufficient).

## 8. Schema profiling (deterministic, privacy-aware)

Probabilistic versus deterministic profiling:

- **Deterministic and safe to compute exactly:** row count, null ratio, distinct count, uniqueness
  ratio, min/max/avg (numeric/temporal), min/max length (text), top-k value *buckets with counts*
  for low-cardinality columns (k ≤ 20), and shape measures (year coverage).
- **Expensive / sampled:** distribution quantiles (skip for V1 except min/max/avg); full distinct
  on huge columns can be approximated later with `count(distinct)` capped.

**Privacy rules (V1):**
1. No raw cell values are persisted in profile artifacts except *bucketed enums* limited to
   non-sensitive columns, k ≤ 20, and only when the column is classified non-sensitive by
   governance rules. Strings are truncated and never sampled if they look like PII
   (email/phone/token/credential heuristics reuse `defaults/guardrails.py` patterns).
2. Numeric profile output stores aggregates only (min/max/avg, null/distinct ratios) — never
   individual values.
3. Profile artifacts inherit the governance classification of their columns at build time; when
   classification is unknown, treat as sensitive (fail closed).
4. Sampling, when used, must not alter a deterministic statement: a sampled distinct count is
   marked `estimated=True` with the sample size.

Candidate detection from profile results:
- identifier: uniqueness ratio ≈ 1 and null ratio ≈ 0
- dimension: distinct count ≤ 100 (or ≤ 5% of rows) and not a measure
- measure: numeric type, not identifier, not flag-like (2 distinct values)
- temporal: date/timestamp type, or numeric epoch-like with wide range
- flag: boolean or 2 distinct values

## 9. Knowledge graphs: schema KG vs data KG

**Data knowledge graph** (NOT built): nodes for every row/entity instance, edges for actual
relationships between data records. That is a graph ETL product with a completely different cost,
privacy, and freshness profile.

**Schema knowledge graph** (built): nodes and edges describing the *data system's structure and
meaning*:

```
Nodes:   Tenant, Connection, Database, Schema, Table, Column,
         Metric, Dimension, Entity, Concept, DataType, Constraint,
         Skill, Tool, ProfileSnapshot
Edges:   OWNS, HAS_SCHEMA, HAS_TABLE, HAS_COLUMN, HAS_METRIC, HAS_DIMENSION,
         REFERENCES, JOINS_WITH, INSTANCE_OF, BELONGS_TO, SEMANTICALLY_RELATED_TO,
         MEASURES, IDENTIFIES, OCCURS_AT, DESCRIBES, VALIDATED_BY
```

Controlled vocabulary: every edge in the list above is intentional; new edge types require an ADR
update. The graph stores metadata and semantics, never row data.

## 10. Graph database comparison (for the abstraction decision)

Facts current as of this review (sources: Neo4j licensing pages/GitHub; FalkorDB docs/GitHub;
Apache AGE; PostgreSQL docs):

| Dimension | Neo4j Community | FalkorDB | PostgreSQL (AGE / recursive CTE) |
|---|---|---|---|
| Model | Property graph | Property graph | Relational + graph extension / SQL recursion |
| Query language | Cypher (+ openCypher lineage) | OpenCypher subset (Redis protocol) | SQL (AGE adds Cypher) |
| License | **GPLv3** (separate server; driver Apache-2.0) | **SSPLv1** (service-use trigger; commercial license available) | PostgreSQL license (permissive) / Apache-2.0 (AGE) |
| Client | Official Python driver (Bolt) | Official Python client (MIT) | `psycopg` (already used) |
| Deployment | Docker image, single server; cluster is Enterprise | Redis module/container; needs Redis-compatible server | Already in the OSS stack for metadata |
| Traversal | Mature, indexed, `EXPLAIN`, path algorithms | Sparse-matrix engine, fast multi-hop | Recursive CTEs workable, ergonomics poor at depth |
| Multi-tenancy | Labels/properties (community); DB-per-tenant is Enterprise | Graphs-as-keys | Schema/table partitioning |
| Ops complexity | Medium (JVM, memory tuning) | Low (small container) | Lowest (already deployed) |
| OSS-friendliness | GPLv3 server is fine when operated as a separate service; well-understood by users | SSPLv1: hosting DataHek as a service would trigger open-sourcing obligations — risky for a product | Best license posture |
| Fit for DataHek V1 | **Initial implementation** — mature Cypher, best tooling, clearest mental model for an inspectable schema graph | Viable future adapter | Fallback adapter (no new component) |

**Decision posture (to be formalized in ADR-004/005/011):** implement `Neo4jGraphRepository`
first, behind `GraphRepository`. Neo4j is a separate service consumed over Bolt — its GPLv3
license does not extend to DataHek's Apache-2.0 code. The abstraction keeps FalkorDB (with its
SSPL caveat) and a PostgreSQL adapter possible without touching the context domain. The context
domain must compile and run with **no graph backend at all** (registry/store still functional;
graph-dependent features report unavailable).

**Where each store belongs (to be detailed in ADR-011):**

```
Context Registry (lifecycle, versions, hashes)   → PostgreSQL (SQLite default)
Context Store (packaged artifacts)               → PostgreSQL / SQLite
Schema Knowledge Graph (semantic relationships)  → Neo4j (optional)
Derived caches (retrieval, compiled packages)    → in-process cache with versioned keys
```

## 11. Where this leads (architecture input for Milestone 2)

1. Context is a **service subsystem** with deterministic engines and one LLM enrichment stage.
2. Two runtime paths: **build-time** (async, staged job → registry → graph) and **request-time**
   (retrieve → compose → compile, bounded, fast).
3. Trust levels and provenance are structural (fields on artifacts), not conventions.
4. The graph is replaceable and optional; the registry and store are not.
5. Grain and governance are correctness inputs; their absence degrades safely (clarify, don't
   guess).
