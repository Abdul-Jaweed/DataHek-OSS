# Context Layer — Lifecycle

**Status:** Milestone 8 deliverable
**Related:** FR-011, FR-014, FR-015 · ADR-006 (registry) · ADR-009 (freshness) · ADR-010 (hashing)

Every context version has exactly one lifecycle state, held by the `ContextRegistry`. State
changes go through `context/lifecycle.py` — illegal transitions raise; nothing writes state
directly.

## States

| State | Meaning |
|---|---|
| `DISCOVERED` | Connection/table scope selected, build not started |
| `PROFILING` / `ENRICHING` | Deterministic stages / LLM enrichment in progress |
| `GENERATED` | Artifacts assembled, not yet published (the registry's initial write per ADR-006) |
| `PENDING_VALIDATION` | Published but awaiting human validation of LLM proposals (`require_validation=True`) |
| `VALIDATED` | Human-reviewed; ready to publish |
| `ACTIVE` | Current published version for the scope |
| `STALE` | Schema hash changed, permission version changed, or age policy expired |
| `REBUILDING` | A rebuild is in flight |
| `DEGRADED` | Projection incomplete (graph unavailable) while registry/store are healthy |
| `FAILED` | A fatal stage failed (e.g. introspection) — retryable |
| `SUPERSEDED` | A newer version published; terminal |

Legal transitions live in `LEGAL_TRANSITIONS` (state diagram in
[architecture.md](architecture.md) §5.1); `SUPERSEDED` is terminal.

## Publish ordering (ADR-006)

`ContextRegistryService.publish` performs an ordered, idempotent write:

```
1. register(record, state=GENERATED)     # registry first
2. store.put(artifact) for every artifact
3. set_state(ACTIVE | PENDING_VALIDATION)  # only after payloads land
4. set_state(previous ACTIVE -> SUPERSEDED)
```

Versioning: `version = previous.version + 1`; each publish gets a fresh `context_id` and links
`supersedes`/`previous_version`, so history is immutable and auditable.

## Invalidation

`invalidate(connection_id)` marks every non-superseded record whose state permits `STALE`
(ACTIVE, VALIDATED, PENDING_VALIDATION, DEGRADED). Records already STALE/SUPERSEDED, and states
that cannot legally go stale, are left untouched; the returned count reports what changed.

Triggers (ADR-009/010):

- `schema_hash` mismatch detected at retrieval or rebuild check → `STALE` + rebuild queued.
- Permission/policy version change → governance is never served stale; record reads stale.
- Profile age beyond policy → profile artifact stale while schema validity is unaffected.

## Build job → lifecycle mapping

`ContextBuildJob.run(...)`:

| Outcome | State effect |
|---|---|
| Introspection fails | No publish; result `state="failed"`; previous ACTIVE untouched |
| Everything decodable | `PUBLISH` → `ACTIVE` (or `PENDING_VALIDATION` when required) |
| Graph unavailable | Stage `degraded`, build still publishes ACTIVE, `degraded=True` |
| Enrichment/model failure | Stage `degraded`, publishes deterministic artifacts only |
| Schema unchanged (`skip_if_current`) | No new version; result `state="current"` |

Rebuild = run the job again (`skip_if_current=False`): a new version is published and the previous
ACTIVE record is superseded.

## Live evidence (M8)

InsForge `unified_events` build: INTROSPECT 2.5s → PROFILE 27.6s → ENRICH 92.5s (real model) →
GRAPH_BUILD 0.8s → QUALITY `sufficient` → PUBLISH 49ms ⇒ **ACTIVE v1**. Re-run ⇒ `current`.
Rebuild ⇒ **v2 ACTIVE**, previous record **SUPERSEDED**.
