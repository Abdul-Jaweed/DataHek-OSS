# Context Layer — REST API

**Status:** Milestone 11 deliverable
**Related:** FR-011 · FR-012 · FR-013 · FR-019 · [context-retrieval.md](context-retrieval.md) · [context-composition.md](context-composition.md)

All routes live in `create_app` (`src/datahek/api/app.py`) following the platform conventions:
optional `_require_auth` dependency, `RequestContext(source="api")` for tenant scoping, and
`DatahekError` mapped through the standard status table (404 `NOT_FOUND`, 422 `VALIDATION`,
502 `CONNECTION_FAILED`, …). Context failures never break question answering — the planner
degrades to the live catalog (FR-019/FR-020).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/connections/{id}/context` | Active record summary; `{"context": null}` when none exists |
| POST | `/connections/{id}/context/build` | Run the staged build job; body `{"enrichment": false}` |
| GET | `/connections/{id}/context/versions?limit=20` | Version history, newest first (FR-011) |
| GET | `/connections/{id}/context/pending` | Reviewable items awaiting validation |
| POST | `/connections/{id}/context/validate` | Apply decisions, publish a new version |
| POST | `/connections/{id}/context/preview` | Retrieve → compose → compile summary for a question |
| GET | `/contexts/{context_id}` | Record summary plus artifact kinds |

### Preview

`{"question": "..."}` → the exact bounded selection and compiled package the planner would see:

```json
{"context_id": "ctx_…", "version": 2, "schema_hash": "…", "stale": false,
 "tables": [{"name": "unified_events", "columns": 40}], "metrics": [],
 "tokens": 995, "dropped": [], "insufficient": "", "trust": "structural",
 "quality": "sufficient"}
```

No active record → 404. `insufficient` is non-empty when governance/grain cannot fit the budget;
`dropped` lists budget-degraded sections.

### Validate

`{"decisions": [{"kind": "granularity", "index": 0, "action": "approve"}]}` where `action ∈
{approve, edit, reject}` and `patch` is the whitelisted edit payload. Unknown kinds → 422; the
response carries the new version's record summary.

### Build

Synchronous in V1 — the staged job (introspect → profile → topology → granularity → taxonomy →
enrich → graph → quality → publish) runs inline and returns its `BuildResult`
(`state`, `context_id`, `version`, `stages`, `quality`, `degraded`, `warnings`). Enrichment is
opt-in per request because it spends model tokens. An async job queue is deferred (M12).

Audit: `context.build` and `context.validate` events are recorded with actor, connection, and
decision counts.

## Planner integration (FR-019)

The planner is wired with the retriever/composer/compiler and, before planning:

1. compiles the active context for the question;
2. if the package is `INSUFFICIENT` → returns a clarification instead of guessing (fail closed);
3. if a package is available → renders the schema block, grain statements, join relationships,
   restricted columns, and package metrics from the package, and skips the live catalog fetch
   (unless a skill needs it);
4. on any context-layer failure or missing record → logs and uses the existing live-catalog path.

`tests/test_planner_context.py` (6) proves both modes; the full pre-existing planner/agent suite
passes unchanged.

## Deferred

- Async build jobs and progress streaming (M12 operations).
- Review-inbox UI on top of `/pending` + `/validate` (web app).
- Package persistence endpoint (`ContextStore.put_package` exists; nothing writes packages yet).

## Tests

`tests/test_context_api.py` (11): status/empty, version ordering, pending listing, validate
publication + unknown-kind 422, preview compile summary + 404, build via overridden job,
record/artifact-kind lookup + 404.

## Live evidence

InsForge, in-process TestClient against the real stack: build (deterministic) → `active` v1 →
`GET /context` → preview question *"What was the revenue by customer over time?"* selected
`ecommerce_sales` (995 tokens, `structural`, `sufficient`) → pending review → one approval
published v2 → versions newest-first → `POST /ask` answered with context-compiled planning.
