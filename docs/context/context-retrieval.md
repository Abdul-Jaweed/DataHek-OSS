# Context Layer — Retrieval

**Status:** Milestone 10 deliverable
**Related:** FR-012 · [context-model.md](context-model.md) · [taxonomy.md](taxonomy.md) · [knowledge-graph-schema.md](knowledge-graph-schema.md)

Retrieval turns a runtime question plus an active context record into the **relevant subset** of
persistent context. It is deterministic — no LLM, no embeddings — and bounded: a hostile
"select everything" question still returns capped slices (FR-012).

## Service

`ContextRetrieverService(registry, store, semantic_store=None)`:

- `retrieve(ctx, connection_id, question, scope="connection", current_schema_hash="") -> RetrievedContext | None`

Reads the `ACTIVE` record and its artifacts through the tenant-scoped store. Returns `None` when no
active record exists — callers decide whether to build or proceed without context; retrieval never
triggers a build.

## Selection algorithm

1. **Tokens.** The question is lowercased, non-alphanumeric characters dropped, and stopwords
   removed (`question_tokens`).
2. **Tables.** Each table scores by name and column-name matches against the tokens, plus metric
   names/descriptions from the semantic store and ontology concept names/synonyms whose `maps_to`
   targets the table. Tables joined by a topology edge to a selected table are pulled in as
   one-hop neighbours. Caps: **8 tables, 40 columns per table** (`_TABLE_CAP`/`_COLUMN_CAP`).
   With no matches at all, the first tables in schema order are returned so the planner still gets
   a usable floor.
3. **Slices.** Profile, granularity, taxonomy, and ontology sections are filtered to the selected
   tables; topology keeps only edges **between selected tables** (join paths re-keyed to match);
   metrics keep only those matching the tokens (semantic-store metrics that referenced dropped
   tables are excluded).
4. **Governance** is always attached in full — sensitivity and permission information is never
   narrowed by relevance.

The result is a `RetrievedContext`: selected `schema`/`profiles`, filtered `topology`/
`granularity`/`taxonomy`/`ontology`, `metrics`, full `governance`, the record's `quality` and
`freshness`, and a `stale` flag set when `current_schema_hash` differs from the record's
`schema_hash` (FR-014 signals the caller; retrieval itself does not mutate state).

## Tests

`tests/test_context_retrieval.py` (9): metric-name selection, column-name selection, join edges
only between selected tables, slice tracking, governance pass-through, missing record → `None`,
stale flag, no-match fallback within caps, stopword tokenization.

## Live evidence

InsForge (deterministic build): question *"What was the revenue by customer over time?"* selected
`ecommerce_sales` with its profile, 995 composed tokens, `stale=False`; a mismatched
`current_schema_hash` returned `stale=True`; an unknown connection returned `None`.
