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
| M7 | Schema Knowledge Graph | Pending |
| M8 | Context Registry, persistence, versioning | Pending |
| M9 | Human semantic validation | Pending |
| M10 | Retrieval, composer, compiler | Pending |
| M11 | SQL agent integration | Pending |
| M12 | Testing, observability, security hardening | Pending |

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

Subsystem specifications produced with their implementation milestones:
`taxonomy.md` / `ontology.md` / `topology.md` / `granularity.md` / `semantic-enrichment.md` (M5),
`graph-abstraction.md` / `neo4j.md` / `knowledge-graph-schema.md` (M6–M7), `lifecycle.md` /
`provenance.md` (M8), `context-retrieval.md` / `context-composition.md` (M10), `api.md` (M11),
`security.md` / `multi-tenancy.md` / `observability.md` / `testing-strategy.md` (M12).

## Non-goals (V1)

No data-level knowledge graph, no vector database / RAG platform, no autonomous agent swarm, no
unrestricted Cypher or SQL generation from LLM output, no credentials in context, no entire-graph
injection into prompts, no Neo4j-specific domain model.
