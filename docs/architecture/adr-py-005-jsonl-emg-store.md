# ADR-PY-005: Durable JSONL EMG store before Postgres/pgvector (WP-08 PR-1)

- Status: ADOPTED
- Date: 2026-08-19
- Spec ref: §13 (EMG), §13.16 / ADR-010 (storage), §15.7–§15.14 (learning, retrieval, seed corpus)
- Decider: Implementing Agent

## Context

WP-08 §2 "Honest Diagnosis" called out that the EMG subsystem was process-local
only — `InMemoryInsightStore`, `TaskMemoryNodeStore`, `CrossTaskEdgeStore` were
plain dicts. Restart the CLI or the FastAPI server and the knowledge was gone.
The seed corpus was empty; there was no `artifacts/` directory on disk. The
retrieval product was a demo, not a product.

ADR-010 (PostgreSQL/pgvector before dedicated graph DB) remains the team-mode
target. But standing up Postgres for a single-tenant, single-developer setup
delays the learning loop without adding value — the bottleneck is *filling*
the store, not querying it.

## Decision

Implement a durable JSONL store as the first production backend. ADR-010
remains queued; we do NOT implement Postgres/pgvector in this track.

Layout (under `{project}/.oiw/emg/` or `{OIW_WORKSPACE}/.oiw/emg/`):

```
.oiw/emg/
  manifest.yaml          # schemaVersion, embedding.backend, embedding.model, embedding.dim
  insights.jsonl         # IntraTaskInsight + promotion state (InsightRecord)
  tasks.jsonl            # TaskMemoryNode including requirementEmbedding + embeddingBackend
  edges.jsonl            # CrossTaskEdge
```

Design rules (WP-08 A-001 acceptance):

1. **Atomic writes**: write to a `.tmp` file in the same directory, then `os.replace`. A killed process cannot leave a truncated JSONL.
2. **`embeddingBackend` is always written** on every task node. The pre-WP-08 `insert_from_requirement` forgot to stamp it — that bug is fixed.
3. **Dim-mismatch protection**: vectors from a different backend/dim are skipped (similarity 0), never mixed. Loading a store whose manifest doesn't match the current embedder sets `_compatible=False`; `search_similar` returns `[]` and tells the operator to run `oiw emg reindex`.
4. **The `EmgStore` Protocol** is a superset of the existing in-memory classes — callers don't care whether they're talking to RAM or disk. `InMemoryInsightStore` / `TaskMemoryNodeStore` / `CrossTaskEdgeStore` stay as test doubles.

## Consequences

- Positive: Durable knowledge survives process restart. The CLI (`oiw emg status|reindex`) and the FastAPI server load the same store, so `GET /api/v1/emg/stats` agrees with `oiw emg status`. Promotion now persists through `JsonlEmgStore` (WP-08 PR-3/A-004).
- Positive: A JSONL store is enough to productize learning for one tenant and one developer. ADR-010 (Postgres/pgvector) is a later extraction, not a prerequisite.
- Positive: The `force_remanifest()` helper enables `oiw emg reindex` to switch backends (e.g. tfidf → gemma) without losing insights or edges.
- Negative: JSONL search is O(N) over all task nodes. Fine for a few hundred; pgvector becomes worth it around 1k nodes (ADR-010's trigger).
- Negative: Cross-process visibility requires a server restart today (the in-memory mirror is loaded once at startup). A file-watcher or poll-on-read would close this; not yet implemented.

## Alternatives considered

- **SQLite + JSON columns**: rejected because it adds a binary artifact to a text-first repo. JSONL diffs cleanly in PRs.
- **Postgres/pgvector now (ADR-010 early)**: rejected per WP-08 §5 A-001 ("Do not implement PostgreSQL/pgvector first. Delays the learning loop. JSONL + manifest is enough for one tenant and one developer. ADR-010 stays queued.").
- **Plain in-memory + dump-on-exit**: rejected because it doesn't survive a SIGKILL or a crash mid-write. Atomic temp-file-then-rename is the minimum bar for durability.

## Migration target

When ADR-010 (Postgres/pgvector) lands, `JsonlEmgStore` becomes a thin
adapter that delegates to pgvector for `search_similar` and reads/writes
JSONL only for export/import. The `EmgStore` Protocol stays the same;
callers don't notice the swap.
