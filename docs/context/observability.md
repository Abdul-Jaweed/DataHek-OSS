# Context Layer — Observability

**Status:** Milestone 12 deliverable
**Related:** FR-016 · NFR-004 · [api.md](api.md) · [lifecycle.md](lifecycle.md)

The Context Layer uses the platform's existing observability infrastructure: `LocalMetrics`
(Prometheus text at `/metrics`) and the JSONL audit trail (searchable at `/audit`). No new
backends, no tenant identifiers in metric labels.

## Metrics

Emitted at the API boundary (`api/app.py`):

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `datahek_context_builds_total` | counter | `outcome=state\|error` | Build requests by terminal state |
| `datahek_context_build_duration_seconds` | summary | — | End-to-end build latency |
| `datahek_context_retrievals_total` | counter | `outcome=hit\|miss\|insufficient\|error` | Preview/retrieval outcomes |
| `datahek_context_retrieval_duration_seconds` | summary | — | Retrieve → compose → compile latency |
| `datahek_context_tokens` | summary | — | Compiled package token estimates |
| `datahek_context_insufficient_total` | counter | — | Packages that could not fit mandatory sections |
| `datahek_context_validations_total` | counter | `outcome=published\|error` | Review submissions |

These sit alongside the existing request/ask metrics (`datahek_requests_total`,
`datahek_ask_results_total`), so context cost and reliability are measurable per endpoint without
extra infrastructure.

## Audit events

| Event | Emitted when | Payload |
|---|---|---|
| `context.build` | `POST /connections/{id}/context/build` completes | `connection`, `state`, `enrichment` |
| `context.validate` | `POST …/context/validate` publishes a version | `connection`, `decisions` |

Both carry actor (API identity when auth is on, `anonymous` otherwise), `resource_ref` (context
id), and `decision=ALLOW`. Build-job internals record stage status in the `BuildResult` rather
than the audit trail — the job can be retried without spamming events.

## What is deliberately not emitted

- No metric labels with org/user/connection ids (cardinality + privacy).
- No artifact contents in audit payloads.
- No per-stage build metrics in V1 (stage timings live in `BuildResult.stages`).

## Verification

`tests/test_context_observability.py` (5): hit/miss/error counters, token and duration
summaries, build outcome, 503 mapping for store failures, and `/audit` events with actor and
decision. Live evidence in the README M12 entry.
