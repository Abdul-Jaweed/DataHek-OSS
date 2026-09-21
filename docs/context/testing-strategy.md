# Context Layer — Testing Strategy

**Status:** Milestone 12 deliverable
**Related:** NFR-010 · [README.md](README.md) · [security.md](security.md) · [observability.md](observability.md)

The Context Layer is tested at four levels. Everything deterministic runs without a database or
model; live infrastructure is opt-in through environment variables so the default suite stays
fast and offline.

## Levels

| Level | Scope | Examples |
|---|---|---|
| Unit | One service, in-memory/temp SQLite | `test_context_retrieval.py`, `test_context_composition.py`, `test_context_taxonomy.py`, `test_context_topology.py`, `test_context_granularity.py`, `test_context_profiler.py`, `test_context_snapshot.py` |
| Contract | One interface, every implementation | `graph_repository_contract.py` (memory + Neo4j), `test_context_serialization.py` (round-trips), `test_context_store_pg.py` |
| Integration | Multi-service flows on SQLite | `test_context_registry.py`, `test_context_build_job.py`, `test_context_validation.py`, `test_context_quality.py`, `test_context_freshness.py`, `test_context_graph_builder.py`, `test_context_api.py` |
| Hardening | Cross-cutting guarantees | `test_context_security.py`, `test_context_degradation.py`, `test_context_observability.py` |

## Conventions

- `unittest` only, run from the repo root:
  `python -m unittest discover tests`.
- Frozen dataclasses and `Protocol` contracts make fakes trivial — no mocking framework.
- Tests seed state through real services (temp SQLite registry/store) instead of patching
  internals; assertions target public behavior.
- Env-gated suites skip cleanly: `DATAHEK_TEST_PG_URL` (PostgreSQL store),
  `DATAHEK_TEST_NEO4J_URL` + `DATAHEK_TEST_NEO4J_PASSWORD` (graph adapter contract).
- Each context module ships its tests in the same commit as its implementation.

## Coverage map (FR → tests)

| Requirement | Primary tests |
|---|---|
| FR-004–008 schema/profiling/semantics | `test_context_snapshot.py`, `test_context_profiler.py`, `test_context_topology.py`, `test_context_taxonomy.py`, `test_context_granularity.py`, `test_context_enrichment.py` |
| FR-009 graph | `test_context_graph_builder.py`, `graph_repository_contract.py` |
| FR-010 human validation | `test_context_validation.py` |
| FR-011 versioning | `test_context_registry.py`, `test_context_api.py` |
| FR-012–013 retrieval/composition | `test_context_retrieval.py`, `test_context_composition.py` |
| FR-014–015 invalidation/rebuild | `test_context_freshness.py`, `test_context_build_job.py` |
| FR-016 observability | `test_context_observability.py` |
| FR-017 graph replaceability | `graph_repository_contract.py` (both adapters) |
| FR-018 security/tenancy | `test_context_security.py`, `test_context_store_pg.py` |
| FR-019 planner integration | `test_planner_context.py` |
| FR-020 degradation | `test_context_degradation.py`, `test_context_build_job.py` |

## Live verification

Milestone evidence runs against real infrastructure outside the unit suite (scripts kept with
the working notes): InsForge PostgreSQL for builds/profiling/validation/ask, Neo4j for the graph
contract and builder, and an in-process TestClient for the M11/M12 REST + observability checks.
Results are recorded per milestone in [README.md](README.md).

## Deferred

- CI-enforced live suites (the workflow exists; workflow-scoped token pending).
- Load/soak testing for large schemas (10k+ tables) — bounded-selection unit tests cover the
  algorithmic side; production numbers come from Enterprise operations.
