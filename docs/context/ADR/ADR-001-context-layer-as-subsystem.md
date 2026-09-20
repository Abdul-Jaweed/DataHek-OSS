# ADR-001: Context Layer as a First-Class Subsystem

**Status:** Accepted (M2)

## Context

DataHek answers questions by assembling schema text, metric definitions, skills, and conversation
history directly inside the planner. That ad-hoc assembly is the *de facto* context system: it has
no persistence, no versioning, no provenance, no freshness, no budget, and no reuse beyond one
code path. The brief requires a Context Layer that is a subsystem in its own right, not helper
functions around a prompt.

## Decision

The Context Layer is a **first-class control-plane subsystem** with:

- its own contracts (`contracts/context.py`), domain services (`context/`), and storage adapters
  (`defaults/context_*.py`, `context/graph/neo4j.py`);
- persistent, versioned context artifacts independent of any single request;
- a request-time path (retrieve → compose → compile) that produces structured Context Packages;
- lifecycle, provenance, quality, and freshness as first-class fields;
- registration in the DI container like every other DataHek subsystem.

A system prompt is one consumer of context. The planner becomes the first consumer of a compiled
package, not the owner of context assembly.

## Alternatives considered

1. **Keep ad-hoc planner assembly and improve it in place.** Rejected: no persistence/versioning/
   provenance, duplicated logic per consumer, no answer for wide schemas or grain correctness.
2. **Embed context generation inside the planner** (build-on-first-request). Rejected: couples
   build cost to user latency, no human validation gate, no reuse by verifier/MCP.
3. **Full external catalog product.** Rejected: violates OSS self-containment and adds a mandatory
   service.

## Trade-offs

- More moving parts and schema surface to maintain.
- Build path must exist before planner benefits are visible.
- Deliberate non-goal: the subsystem must not become an agent swarm.

## Consequences

- New contract package boundary; Enterprise can override any context service via DI.
- Existing planner inputs migrate behind the compiler; behavior with the Context Layer disabled
  must remain unchanged (tested).
- Documentation and ADR obligations attach to a named subsystem.

## Future Migration

If a graph or storage backend changes, only adapters change. If the subsystem proves too heavy for
small schemas, the compiler can emit a minimal package while the registry stays idle — the boundary
allows it without redesign.
