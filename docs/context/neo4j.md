# Context Layer — Neo4j Adapter

**Status:** Milestone 6 deliverable
**Related:** ADR-004 (Neo4j first) · ADR-005 (abstraction) · ADR-011 (storage split)

Neo4j is the initial Schema Knowledge Graph backend. It runs as an **optional, separate service**;
the default OSS stack works without it and graph-dependent features degrade to
`DEGRADED`.

## Installation and configuration

```bash
pip install "datahek-core[graph]"        # adds neo4j>=5.20 (no new core dependencies)
docker compose --profile graph up -d neo4j
```

| Variable | Default | Purpose |
|---|---|---|
| `DATAHEK_NEO4J_URL` | *(empty)* | Bolt URL; unset disables graph registration entirely |
| `DATAHEK_NEO4J_USER` | `neo4j` | Database user |
| `DATAHEK_NEO4J_PASSWORD` | *(empty)* | Password (compose default: `datahek-graph`) |
| `DATAHEK_NEO4J_DATABASE` | *(default db)* | Optional named database |

When `DATAHEK_NEO4J_URL` is set, `build_default_container` registers `Neo4jGraphRepository` under
the `GraphRepository` contract; Enterprise or alternative backends override the same binding.

## Schema

One label, prefixed properties — no dynamic labels and no property-name interpolation:

- `(:DataHekNode {id, label, org_id, project_id, context_version, schema_hash, provenance,
  created_at, updated_at})` plus user properties stored as `p_<name>` (flattened strings because
  Neo4j properties are primitives/arrays only).
- Relationships use the **controlled vocabulary** as their type (`HAS_TABLE`, `REFERENCES`, …) with
  `id`, `org_id`, `context_version`, `schema_hash`, `provenance`, `confidence` properties.
- Constraints/indexes created by `init_schema()`: unique `id`, index on `org_id`, composite index
  on `(org_id, label)`.

Safety properties:

- Relationship types are validated against the closed vocabulary **before** interpolation;
  property keys must match `^[A-Za-z0-9_]+$`; numeric bounds (limit/depth) are int-cast and capped.
- Every read filters `org_id`; cross-tenant access returns nothing.
- `MERGE` on stable ids makes graph rebuilds idempotent and duplicate-free.

## Operational notes

- **One event loop per driver.** The async driver is loop-affine; create the repository inside the
  application's single loop (the API/MCP containers do; the contract suite uses one loop per test).
- **`localhost` on Windows** may resolve to IPv6 first while Docker publishes IPv4 — use
  `bolt://127.0.0.1:7687` in local development to avoid slow connection retries.
- `health_check()` returns a boolean (used by the M7 build job to enter `DEGRADED` instead of
  failing the build).
- The graph is a **projection**: it can be rebuilt from the registry/store at any time (M7+).

## Licensing

Neo4j Community Edition is **GPLv3** and runs as a separate server process; DataHek (Apache-2.0)
connects over Bolt with the official driver (Apache-2.0), so no license obligations extend to
DataHek code. FalkorDB (SSPLv1) remains an option for internal-only deployments per ADR-004.

## Verification

`DATAHEK_TEST_NEO4J_URL=bolt://127.0.0.1:7687 DATAHEK_TEST_NEO4J_PASSWORD=datahek-graph python -m
unittest discover tests -p "test_graph_neo4j.py"` — 13/13 contract tests, ~1.5s locally.
