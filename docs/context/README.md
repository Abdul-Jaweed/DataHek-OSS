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
| M2 | Architecture, context model, SRD, ADRs, diagrams | **Complete — in review** |
| M3 | Context domain model + contracts | Pending |
| M4 | Schema discovery + profiling | Pending |
| M5 | Taxonomy, ontology, topology, granularity | Pending |
| M6 | Graph abstraction + Neo4j adapter | Pending |
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
- [`ADR/`](ADR/) — 13 architecture decision records (subsystem boundary, persistent vs runtime,
  schema KG, Neo4j, graph abstraction, registry, package model, human validation, freshness, change
  detection, storage split, multi-tenancy, LLM vs deterministic)

Subsystem specifications produced with their implementation milestones: `schema-profiling.md` (M4),
`taxonomy.md` / `ontology.md` / `topology.md` / `granularity.md` / `semantic-enrichment.md` (M5),
`graph-abstraction.md` / `neo4j.md` / `knowledge-graph-schema.md` (M6–M7), `lifecycle.md` /
`provenance.md` (M8), `context-retrieval.md` / `context-composition.md` (M10), `api.md` (M11),
`security.md` / `multi-tenancy.md` / `observability.md` / `testing-strategy.md` (M12).

## Non-goals (V1)

No data-level knowledge graph, no vector database / RAG platform, no autonomous agent swarm, no
unrestricted Cypher or SQL generation from LLM output, no credentials in context, no entire-graph
injection into prompts, no Neo4j-specific domain model.
