# Work Package WP-08: Productize the Learning Loop — Persist EMG, EmbeddingGemma-300m, Real Tenant, Held-Out Proof

**Phase:** Productization of the Experience Memory Graph (before UI work)
**Prerequisite:** WP-04 through WP-07 machinery exists in-tree. This package treats that machinery as a prototype, not as a product.
**Spec sections:** §13 (EMG), §13.16 / ADR-010 (storage), §15.7–§15.14 (learning, retrieval, seed corpus), §18 (tenant connectivity)
**Branch convention:** `feature/wp08-<track>-<task-number>`
**Hard gate:** The web UI is out of scope until Track D (held-out test artifact) passes. Do not start Track E early.

---

## 1. Objective

Turn OIW from a mocked, in-memory demo into a system that **actually remembers** and **actually talks to a BTP tenant**.

The developer must complete these steps **in this order**:

1. Persist the EMG (insights, task nodes, embeddings, edges) to disk so knowledge survives process restart.
2. Replace TF-IDF as the default embedder with **EmbeddingGemma-300m**, and re-embed everything under that model.
3. Reinitiate CodeJam learning against the persisted Gemma index (not synthetic IR, not in-memory TF-IDF).
4. Pull **existing artifacts from the real BTP tenant**, import them, embed them, persist them.
5. Create a **separate held-out test artifact** (not in the learned set) and prove retrieval helps before any UI work.
6. Only then make the web UI load and display that persisted knowledge fluidly.

This package exists because the previous work packages built shelves. They did not put durable books on them, and they never opened the real library (the tenant).

---

## 2. Honest Diagnosis (read this before writing code)

> **Update 2026-08-19 (post WP-08 PR-1 through PR-7):** the table below records
> the original diagnosis at WP-08 kickoff. Each row has a "✅ Resolved by" note
> in the right column where applicable. The "What *is* durable today" section
> has also been updated to reflect the new `JsonlEmgStore` substrate.
> Rows that are NOT yet resolved are tagged "⏳ Pending".

The README and DEVELOPMENT_LOG originally over-claimed. As of WP-08 PR-1 through PR-7, the code now matches (or honestly exceeds) those claims for the substrate, parser, tenant read path, and CodeJam corpus. The remaining gaps are tracked on OW-030 (held-out proof, Track D) and OW-031/OW-032 (write path + UI).

| Claim | What the code actually does | Status (2026-08-19) |
|-------|-----------------------------|---------------------|
| "EMG Phase B+C operational" | ~~Graph matching, insight compiler, retriever, and promotion **exist**. `InMemoryInsightStore`, `TaskMemoryNodeStore`, `CrossTaskEdgeStore` are **process-local dicts**. Restart the CLI or the API server and the knowledge is gone.~~ **NOW DURABLE**: `JsonlEmgStore` (PR-1) persists insights + task nodes + edges + manifest to `.oiw/emg/{manifest.yaml, insights.jsonl, tasks.jsonl, edges.jsonl}` with atomic writes. CLI `oiw emg status|reindex` (PR-3) + FastAPI server loads store on startup (PR-3) + promotion writes through the durable store (PR-3/A-004). Restart the server and the corpus survives. | ✅ Resolved by PR-1, PR-3, PR-3/A-004 |
| "Seed corpus populated" | ~~`packages/seed-corpus/` has Python pipelines and YAML catalogs. There is **no** `artifacts/` directory.~~ **NOW POPULATED**: 7 CodeJam iFlows (PR-6) under `packages/seed-corpus/artifacts/codejam-*/` + 1 tenant artifact (PR-7) under `packages/seed-corpus/artifacts/tenant-Testpackage01-Get_ExchangeRates_DEV/`. Each has `flow.yaml` + `import-report.yaml` + `metadata.yaml` (`provenance.source = sap-codejam` or `tenant`). Retrieval proof at `docs/emg/wp08-codejam-retrieval.yaml`. | ✅ Resolved by PR-6, PR-7 |
| "TF-IDF is fine until retrieval is a bottleneck" (WP-07 §14) | ~~`TfidfEmbedder` is a fixed ~60-term bag over OIW vocabulary. It cannot match paraphrases. `FastembedEmbedder` (MiniLM) exists but `oiw[embeddings]` is **not declared**.~~ **NOW DECLARED + GEMMA AVAILABLE**: `apps/cli/pyproject.toml` has `[project.optional-dependencies] embeddings = ["sentence-transformers>=3.0", "torch"]`. `GemmaEmbedder` (PR-2) implements `google/embeddinggemma-300m` with Matryoshka dim truncation, falls back to a deterministic hash-based pseudo-embedding when `sentence-transformers` is not installed. `create_embedder("auto")` auto-selects gemma → fastembed → openai → tfidf. CI stays on TF-IDF per WP-08 §10. | ✅ Resolved by PR-2 (best-effort — real Gemma requires `pip install 'oiw[embeddings]'`, tracked on OW-033) |
| "Real SAP CI adapter (OW-010)" | ~~`SapCiTenantAdapter` implements list/download/upload/deploy against `/api/v1`. It is **not** the default. No live tenant job exists.~~ **NOW REAL (read-only)**: `SapCiTenantAdapter` (Track 0, ~280 lines) implements `connect`, `list_packages`, `list_artifacts`, `download_artifact`, `get_artifact_version`, `get_artifact_digest` against the live BTP tenant via Basic auth. `build_tenant_adapter()` factory respects `OIW_USE_REAL_TENANT=1`. `oiw tenant ping|list|artifacts|pull` CLI commands work end-to-end. Write path (`upload_package`/`deploy`/`poll_deployment`) stays NotImplementedError per WP-08 §C-004. | ✅ Resolved by Track 0 (read path); ⏳ write path pending on OW-031 (Track D-004) |
| "CodeJam ingested" | ~~One export ZIP lives at `packages/test-fixtures/real-sap/...`. Import status is **PARTIAL**. Five `callActivity` steps are `unsupported`. `real_ingestion.py` **invents a minimal HTTP sender flow** when the parser fails.~~ **NOW FIXED**: PR-5 added `_classify_call_activity()` that reads each callActivity's `<ifl:property><key>activityType</key>` block. `_ACTIVITY_TYPE_MAP` covers 20 SAP CI activityTypes. Real-tenant before/after: 2 → 6 recognized components. `scripts/ingest_codejam.py` (PR-6) walks the cloned SAP-samples CodeJam repo, ingests 7 distinct iFlows (5 "Request Employee Dependants" variants + 2 "Send BP Dependants Request Log to BigQuery" variants), persists redacted IR + import report + metadata per artifact. No skeletonization — `real_ingestion.py`'s `create_pattern_from_analysis()` is bypassed by the new script (the circularity trap is closed for CodeJam). | ✅ Resolved by PR-5, PR-6 |
| "Web UI is substantially complete" | `apps/web/src/App.tsx` is a 552-line god component. EMG panel reads `/api/v1/projects/{id}/emg/insights`, which is a module-level dict populated **only in tests** (`populate_emg_api`). Server startup in `oiw_server/main.py` never loads a corpus. Empty panel is the real UX. | ✅ Server-side resolved (PR-3): server NOW loads the persisted store on startup so `/api/v1/emg/stats` returns real counts + backend/dim/path. ⏳ UI components themselves unchanged (still a god component) — **Track E (PR-10) is now AUTHORIZED** since the Track D gate passed (2026-08-19). The proof is at `docs/emg/wp08-held-out-proof.yaml`. |
| "`oiw learn` CLI" (WP-07) | ~~Learning session dataclasses exist under `apps/cli/oiw/learn/`. **No** `oiw learn` Click group is registered. Only `oiw emg report` and `oiw emg provenance` exist.~~ **STILL TRUE**: `oiw learn` is still not registered. WP-08 §6 B-004 explicitly says: "WP-07 Track B (failed-to-expert pairs) is valuable but is **not** the productization bottleneck. If time is short, skip new learning sessions until Track D." Promotion persistence (PR-3/A-004) is the durable-substrate win; the learn CLI is deferred. | ⏳ Pending — explicitly deferred per WP-08 §6 B-004 |

### What *is* durable today (updated 2026-08-19)

- **EMG substrate** (NEW, WP-08 PR-1): `.oiw/emg/{manifest.yaml, insights.jsonl, tasks.jsonl, edges.jsonl}` with atomic writes + dim-mismatch protection. Survives CLI/server restart.
- Agent **trajectories** as YAML under `.oiw/trajectories/{id}.yaml` (`apps/cli/oiw/agent/trajectory.py`). This is the raw log, not the EMG.
- Mock-tenant state under `.oiw/mock-tenant/` (irrelevant once the real tenant is on).
- Avoid-pattern catalog YAML (static file, not a store).
- **CodeJam corpus** (NEW, WP-08 PR-6): 7 redacted IR + import report + metadata under `packages/seed-corpus/artifacts/codejam-*/`.
- **Tenant corpus** (NEW, WP-08 PR-7): redacted IR + import report + metadata for the live-tenant artifact under `packages/seed-corpus/artifacts/tenant-*/`. Original ZIP stays in the gitignored cache.

### Circularity trap (do not repeat) — CLOSED for CodeJam

WP-07's own warning: if the import parser cannot handle a real iFlow, `create_pattern_from_analysis()` in `packages/seed-corpus/real_ingestion.py` fabricates a sender.http → (optional validator/script/xslt) → receiver.http skeleton. Promoting that as `provenance.source = "sap-codejam"` teaches the EMG OIW's guesses, not SAP's artifact.

**Resolved (WP-08 PR-6):** the new `scripts/ingest_codejam.py` bypasses `create_pattern_from_analysis()` entirely. It walks the cloned CodeJam repo, extracts every iFlow, parses each with the fixed BPMN2 parser (PR-5), and persists the redacted IR + import report. Unknown callActivities are preserved as `unsupported_call_activities` with raw properties — never skeletonized. The circularity trap is closed for CodeJam ingestion.

---

## 3. Sequencing Rule

```
P0 tenant smoke ─┐
                 ├──► P1 persist + EmbeddingGemma
                 │         │
                 │         ▼
                 │    P2 CodeJam re-ingest (public, local)
                 │         │
                 └────────►P3 tenant artifact ingest (needs P0 + P1)
                           │
                           ▼
                      P4 held-out test artifact  ← GATE
                           │
                           ▼
                      P5 UI (only after P4 is green)
```

- P0 and P1 can overlap: confirm the tenant answers OData while the store is being built.
- P2 does **not** need the tenant. Do not wait on BTP credentials to re-learn CodeJam.
- P3 must not start until P1's store can round-trip an embedding and an insight.
- P4 must use an artifact **that was not ingested in P2 or P3**.
- P5 is forbidden until P4's retrieval proof is written down.

Do **not** "just fix the UI so it feels better" in parallel. The panel is empty because the store is empty. Filling the store is the UI fix.

---

## 4. Track 0 — BTP Tenant Smoke (does not learn yet)

**Goal:** Prove `SapCiTenantAdapter` against the real tenant, once. No ingest, no deploy of product content.

### T0-001: Credentials and profile

The adapter already resolves secrets from the environment (`apps/cli/oiw/tenant/credentials.py`):

```
# profile: examples/order-to-s4/environments/dev.yaml
#   tenantUrl: ${DEV_TENANT_URL}
#   auth.tokenUrl: ${DEV_TOKEN_URL}
#   auth.credentialRef: sap-dev-api-client

export DEV_TENANT_URL="https://<tenant>-tmn.hci.<region>.hana.ondemand.com"
export DEV_TOKEN_URL="https://<subdomain>.authentication.<region>.hana.ondemand.com/oauth/token"
export OIW_CRED_SAP_DEV_API_CLIENT_USERNAME="<client-id>"
export OIW_CRED_SAP_DEV_API_CLIENT_PASSWORD="<client-secret>"
export OIW_USE_REAL_TENANT=1
```

Add the same keys to `.env.example` (values blank). Never commit a filled `.env`.

**Acceptance:** `oiw deploy status --profile dev --package-id <any-existing-package>` returns a real version or a precise 404 from the tenant, not mock JSON under `.oiw/mock-tenant/`.

### T0-002: Live connectivity script (manual, not CI)

Add `scripts/tenant_smoke.py` (or `oiw tenant ping`) that:

1. Loads the `dev` profile.
2. Forces `SapCiTenantAdapter` (ignore the mock even if the env flag is unset, but still honor it in production CLI).
3. `GET /IntegrationPackages?$top=5`.
4. Prints package id, name, artifact count. Redact the tenant hostname in any log that might be committed.

**Acceptance:** Developer can list ≥ 1 package from the tenant. Failures are `SapCiTenantError` with status code and OData message, not a traceback from the mock.

### T0-003: Document the upload constraint

`SapCiTenantAdapter.upload_package` can **only update an existing package**. Creating a new package is a tenant-UI / transport operation. Track D (held-out artifact) will need an empty package created by a human on the tenant first. Write this into `docs/contributor-guide/` so Track D is not blocked by surprise.

**Do not ingest yet.** Listing is enough.

---

## 5. Track A — Persistent EMG + EmbeddingGemma-300m

**This is the substrate. Everything else is blocked on it.**

### A-001: On-disk EMG store (replace the dicts)

Keep the in-memory classes as a test double. Introduce a durable store with the **same interface** so `EMGRetriever` does not care.

**Recommended first store (local-first, no Postgres yet):**

```
.oiw/emg/
  manifest.yaml          # schemaVersion, embedding.backend, embedding.model, embedding.dim
  insights.jsonl         # IntraTaskInsight + promotion state
  tasks.jsonl            # TaskMemoryNode including requirementEmbedding + embeddingBackend
  edges.jsonl            # CrossTaskEdge
  avoid-patterns.yaml    # copy or pointer to catalog, plus session-learned patterns
  vectors.npy            # optional; embeddings may live inline in tasks.jsonl for v1
```

Default root: `{project}/.oiw/emg/` for project-scoped knowledge, plus a workspace-level `{OIW_WORKSPACE}/.oiw/emg/` for the seed/tenant corpus. The CLI and the API server **must load the same path**.

Do **not** implement PostgreSQL/pgvector in this track. ADR-010 remains the team-mode target. A JSONL store is enough to productize learning; Postgres is a later extraction. Put an `EmgStore` protocol in `apps/cli/oiw/emg/store.py`:

```python
class EmgStore(Protocol):
    def load(self) -> None: ...
    def save(self) -> None: ...          # atomic (write temp + rename)
    def upsert_insight(self, record) -> str: ...
    def upsert_task(self, node) -> str: ...
    def upsert_edge(self, edge) -> str: ...
    def search_similar(self, vector, top_k, min_similarity) -> list: ...
```

`JsonlEmgStore` implements it. `InMemoryInsightStore` / `TaskMemoryNodeStore` become the RAM backend used by unit tests.

**Acceptance:**

- [ ] `store.upsert_task(...)`; new `JsonlEmgStore(path)` in a second process; `search_similar` returns the same node.
- [ ] Atomic writes: a killed process cannot leave truncated JSONL.
- [ ] `embeddingBackend` is **always** written (`insert_from_requirement` currently forgets it — fix that).
- [ ] Vectors from a different backend/dim are skipped (similarity 0), never mixed.
- [ ] Existing in-memory tests still pass by injecting the RAM store.

### A-002: EmbeddingGemma-300m as the default product backend

Add a fourth backend in `apps/cli/oiw/emg/embedding.py`:

| Backend | When | Dim | Notes |
|---------|------|-----|-------|
| `gemma` | **default for local/dev/tenant learning** | 768 (or documented Matryoshka truncate) | `sentence-transformers` + `google/embeddinggemma-300m` |
| `fastembed` | optional lighter local | 384 | keep |
| `openai` | if `OIW_EMBEDDING_API_*` set | model-defined | keep |
| `tfidf` | **CI only** | ~60 | keep as fallback; never the product default |

Wire it:

```
# apps/cli/pyproject.toml
[project.optional-dependencies]
embeddings = [
  "sentence-transformers>=3.0",
  "torch",            # CPU wheel is fine
]
```

Env:

```
OIW_EMBEDDING_BACKEND=gemma          # product default when extras installed
OIW_EMBEDDING_MODEL=google/embeddinggemma-300m
OIW_EMBEDDING_DIM=768
```

`create_embedder("auto")` becomes: gemma if sentence-transformers + model cache present → fastembed → openai → tfidf.

**License:** EmbeddingGemma is under Google's Gemma terms, not Apache-2.0. Do **not** vendor weights. Document in `NOTICE` that the optional extra downloads a Gemma-licensed model at first use. CI must not require the download (`OIW_EMBEDDING_BACKEND=tfidf` in GitHub Actions).

**Acceptance:**

- [ ] `RequirementEmbedder().backend_name == "gemma"` when extras are installed.
- [ ] Two paraphrases of the same CodeJam requirement have cosine ≫ TF-IDF's (write a golden test with cached vectors so CI does not need the model; a `@pytest.mark.embeddings` live test is manual/nightly).
- [ ] Manifest records `{backend, model, dim}`. Loading a store whose manifest does not match the current embedder **refuses to search** and tells the operator to re-embed (`oiw emg reindex`).
- [ ] CI stays green without Hugging Face.

### A-003: Load the store in the CLI and the API server

Today `populate_emg_api()` is test-only and `EMGRetriever()` constructs empty RAM stores.

- CLI: `oiw emg status` prints backend, model, dim, insight count, task count, edge count, store path.
- CLI: `oiw emg reindex` re-embeds every task node with the current model and rewrites the store.
- Server: on startup, load `{OIW_WORKSPACE}/.oiw/emg/` into the retriever **and** into the REST handlers. Delete the process-global `_INSIGHT_STORE` dict or make it a wrapper over `EmgStore`.
- Agent orchestrator: construct `EMGRetriever` from the same store path, not a fresh empty store.

**Acceptance:** Restart uvicorn. `GET /api/v1/emg/stats` returns the counts that `oiw emg status` prints. Kill the process, restart, counts unchanged.

### A-004: Promotion writes through the store

`packages/seed-corpus/promote.py` currently builds an `InMemoryInsightStore` and returns it to the caller, who drops it. Change the promotion pipeline so `PROJECT_APPROVED` insights and task nodes are `upsert_*`'d. Seed discount (0.8) stays for synthetic; **real** CodeJam/tenant provenance uses confidence 1.0 subject to reviewer tag.

**Acceptance:** `python -m packages.seed_corpus.promote` (or `oiw emg promote --from trajectories/`) leaves a non-empty `.oiw/emg/insights.jsonl`.

---

## 6. Track B — Reinitiate CodeJam Learning (public artifacts, persisted Gemma)

**Goal:** The EMG's first real books. Local only. Tenant not required.

### B-001: Clone and inventory the full CodeJam

```bash
git clone --depth 1 \
  https://github.com/SAP-samples/connecting-systems-services-integration-suite-codejam \
  /tmp/sap-codejam
```

Inventory every iFlow (`.iflw`, nested ZIPs under exercises). The current fixture ZIP already contains **7 iFlow variants** in one export — split them. Do not treat the outer ZIP as one artifact.

Write `packages/seed-corpus/artifacts/codejam-<exercise-id>/` with:

- imported IR (`flow.yaml`) **only if** `oiw import` + `oiw validate` succeed at `FULL` or honest `PARTIAL` with ≥ N recognized nodes
- `import-report.yaml` (already the right format)
- `metadata.yaml` with `provenance.source: sap-codejam`, `license: Apache-2.0`, `isReal: true`

**Acceptance:** ≥ 8 distinct CodeJam artifacts on disk **or** a written inventory showing the repo has fewer, with every skipped artifact listed and why.

### B-002: Fix the import parser gaps that currently invent knowledge

From `import-report.yaml` of the existing fixture, the parser failed to classify:

- `callActivity:GET apiKey from SecureStore` (tenant-required — mark `tenant-required`, do not fake a node)
- `callActivity:Convert BP response to XML`
- `callActivity:Country not supported error` (error subprocess)
- `callActivity:Get Employee Country`
- `callActivity:Delete Request Log entry`

Work in `apps/cli/oiw/compiler/sap_import.py` / `sap_flow_parser.py`. Prefer classifying from `ifl:property` keys over guessing from the activity name.

**Rule:** if classification fails, the component stays `unsupported` in the import report. `real_ingestion.py` must **stop** calling `create_pattern_from_analysis()` for CodeJam/tenant sources. Delete or gate that function behind `source == "synthetic"`.

**Acceptance:** Re-import of `source-with-groovy.zip` has fewer `unsupported` callActivities than today (target: 0 misclassified; SecureStore may remain `tenant-required`). No generated skeleton flow is promoted as CodeJam.

### B-003: Expert trajectories from the real IR, then persist

For each successfully imported artifact:

1. `synthesize_expert_trajectory()` from the **imported IR**, not from a guessed skeleton.
2. Promote through the existing workflow, writing to the Jsonl store.
3. Embed the normalized requirement with Gemma; stamp `embeddingBackend: gemma`.
4. Tag provenance.

Then rebuild cross-task edges (`packages/seed-corpus/cross_task_pipeline.py`) **from the persisted task nodes**, not from RAM.

**Acceptance:**

- [ ] `oiw emg status` shows N ≥ number of imported CodeJam artifacts.
- [ ] Every insight has `provenance.source = sap-codejam`.
- [ ] A paraphrased requirement for "request employee dependants over HTTPS" retrieves the CodeJam insight at similarity above the configured min (record the score in `docs/emg/wp08-codejam-retrieval.yaml`).
- [ ] An unrelated SFTP requirement does **not** retrieve it (false-positive check).

### B-004: Do not run failed-to-expert sessions against CodeJam yet unless cheap

WP-07 Track B (failed-to-expert pairs) is valuable but is **not** the productization bottleneck. If time is short, skip new learning sessions until Track D. The tenant artifacts in Track C will produce more authentic expert trajectories than synthetic failure modes.

If you do run sessions: persist them under `packages/seed-corpus/learning-sessions/` **and** into the EMG store. Wire `oiw learn start|finalize|extract` (still missing) only if you need it for Track D. Do not block Track C on the learn CLI.

---

## 7. Track C — Learn From Existing Tenant Artifacts

**Goal:** The EMG learns the integration content that already lives on this BTP tenant. Read-only against the tenant.

Depends on: T0-002 green, A-003 green, B-003 at least able to persist one artifact (so the pipeline is proven).

### C-001: `oiw tenant pull`

New command (thin wrapper over `SapCiTenantAdapter.download_package` + `oiw import`):

```
OIW_USE_REAL_TENANT=1 oiw tenant pull --profile dev --all \
  --out packages/seed-corpus/artifacts/tenant-<packageId>/
```

Behavior:

1. List packages.
2. Download each `$value` ZIP to a gitignored cache (`.oiw/tenant-cache/`) — **do not commit tenant ZIPs** (they may contain hostnames, credentials in Groovy, customer IP).
3. Import to IR.
4. Run the existing redactor (`apps/cli/oiw/agent/redaction.py`) over IR config, scripts, and import reports before anything is eligible for the EMG.
5. Write `metadata.yaml`: `provenance.source: tenant`, `tenantHash: sha256(tenantUrl)[:12]`, `packageId`, `isReal: true`, `confidentialityScope: project`.

**Acceptance:** At least one real tenant package becomes IR on disk. Secrets/URLs do not appear in anything that could be committed. Add `.oiw/tenant-cache/` and `packages/seed-corpus/artifacts/tenant-*` to `.gitignore` unless a reviewer explicitly allowlists a redacted IR.

### C-002: Import what the parser can; quarantine the rest

Same rule as CodeJam. Parser gaps go to `docs/emg/tenant-import-gaps.md` (component type, ifl property keys, why). Do not skeletonize.

For artifacts that import as `PARTIAL`, still embed and persist **if** the recognized subgraph is a real integration pattern (sender + ≥ 1 processor + receiver). Record `importResult.status` on the task node so retrieval can down-rank PARTIAL vs FULL.

### C-003: Embed, promote, persist

Same promotion path as B-003. Source tag `tenant`. Confidence not discounted.

Build cross-task edges between CodeJam nodes and tenant nodes when similarity ≥ threshold. This is the first time public patterns and this customer's patterns share a graph.

**Acceptance:**

- [ ] `oiw emg status` shows `source=tenant` task nodes > 0.
- [ ] `oiw emg provenance` (extend it) lists tenant vs codejam vs synthetic counts.
- [ ] Cross-task search from a tenant requirement can return a CodeJam neighbour *or* another tenant neighbour, with scores logged.

### C-004: Do not deploy, do not mutate tenant content

Track C is **GET-only**. No `upload_package`, no `DeployIntegrationArtifact`. The tenant is a library, not a scratchpad.

---

## 8. Track D — Held-Out Test Artifact (the proof)

**This is the gate. UI work is unauthorized until this track's report exists.**

The test artifact must **not** be one of the CodeJam exercises and **not** a copy of a tenant package that was ingested. If it is in the training set, retrieval "success" is memorization.

### D-001: Design the held-out artifact

Pick a requirement that is **structurally similar** to something already learned (so retrieval has a chance) but **not identical**.

Example shape (adjust to whatever the tenant actually contains):

- Learned: CodeJam "HTTPS → HTTP GET employee dependants, JSON-to-XML, Groovy for API key".
- Held-out: "HTTPS sender → content modifier for correlation id → JSON-to-XML → HTTP receiver to a **different** business API, with an error subprocess on 4xx."

Create it as a **new OIW project**: `examples/held-out-<name>/`. Git is the source of truth. Do not start from a tenant export of a learned package.

Write `examples/held-out-<name>/REQUIREMENT.md` with the natural-language requirement that will be fed to the agent.

### D-002: Baseline (EMG off)

```
oiw agent --no-emg "$(cat examples/held-out-<name>/REQUIREMENT.md)" \
  --project examples/held-out-<name>
```

(If `oiw agent` is not wired, use the existing orchestrator entry used by `tests/agent_eval/`.)

Record: plan steps, whether validation passed, whether the agent needed the LLM, token/latency if available, structural match against a human-written expected flow.

### D-003: With EMG (persisted Gemma index from B+C)

Same requirement, same base revision, EMG on. Record:

- which insight ids were retrieved (intra + cross-task)
- similarity scores
- whether avoid-patterns fired
- whether the plan incorporated a retrieved workflow
- validation/test result

**Pass criteria (all required):**

1. At least one retrieved insight has `provenance.source` in `{sap-codejam, tenant}` — not `synthetic`.
2. Retrieval similarity ≥ the min threshold in the store manifest.
3. The with-EMG plan is measurably better than baseline on at least one of: fewer validator errors, higher structural overlap with the intended flow, or a mechanics-first hit (LLM not required).
4. The held-out project id does **not** appear as a `taskId` in the store before the run (prove it was not ingested).

Write results to `docs/emg/wp08-held-out-proof.yaml`.

### D-004: Optional tenant deploy of the **held-out** artifact only

Only after D-003 passes locally.

1. Human creates an empty integration package on the tenant (API cannot create it — T0-003).
2. `OIW_USE_REAL_TENANT=1 oiw deploy ... --upload --execute --verify` against **that** package id.
3. Capture `deployment_success` in the trajectory reward vector.
4. If deploy fails, that failure is a **new** learning session (failed-to-expert), persisted, not a reason to open the UI.

Do not deploy CodeJam content. Do not overwrite existing tenant packages.

---

## 9. Track E — UI, only after Track D

The UI is not the productization problem. It is a window onto a store that today does not exist.

### E-001: Make the window honest

- Server loads `EmgStore` at startup (already A-003). The panel in `EmgInsightPanel.tsx` will then show real counts.
- Surface backend/model/dim and store path in the EMG stats strip so a Gemma index cannot be confused with TF-IDF.
- Wire co-pilot `Suggest` to the same retriever the CLI uses. `emgUsed` / "⚡ EMG hit" must be true only when `RetrievalResult.found` is true.

### E-002: Fluidity (OW-029, finally)

Only after E-001:

- Finish extracting remaining god-component state from `App.tsx` (canvas already has `FlowCanvas` / `PalettePanel` / `PropertiesPanel`; the data-loading and pending-ops machine still live in `App`).
- Pending ops: optimistic local state with a single PATCH on Save is fine; fix the cases that reload the whole flow on every palette drop if they still exist.
- Loading and error states per panel, not one global `error` banner.
- Playwright: one test that starts the server with a fixture `EmgStore` and asserts the insight list is non-empty; one test that the held-out requirement shows an EMG hit badge.

### E-003: Still out of scope

- Auth (OW-005)
- Kotlin/Spring rewrite
- Pixel-level SAP UI
- Multi-tenant isolation beyond `confidentialityScope: project`

---

## 10. What Not To Do

| Temptation | Why not |
|------------|---------|
| "Upgrade TF-IDF later" | Retrieval **is** the product. Gemma is Track A, not a polish item. |
| Implement Postgres/pgvector first | Delays the learning loop. JSONL + manifest is enough for one tenant and one developer. ADR-010 stays queued. |
| Fix the UI so the empty EMG panel "looks better" | Empty is correct. Fill the store. |
| Promote `create_pattern_from_analysis()` skeletons as CodeJam/tenant knowledge | Recreates the circularity WP-07 was written to kill. |
| Train and test on the same tenant package | Memorization, not learning. Track D exists to prevent this. |
| Default `OIW_USE_REAL_TENANT=1` in CI | CI has no tenant. Keep mock as CI default. |
| Commit tenant ZIP exports | Customer content, possible secrets. Cache gitignored. |
| Mix Gemma vectors with leftover TF-IDF vectors | Dim mismatch already returns 0, but a half-reindexed store silently degrades. `oiw emg reindex` or refuse. |
| Deploy to an existing production package | Track D creates a dedicated package. |

---

## 11. Suggested PR order (one PR per line, mergeable)

| PR | Track | Title | Depends on |
|----|-------|-------|------------|
| PR-1 | A-001 | `EmgStore` protocol + `JsonlEmgStore` + stamp `embeddingBackend` | — |
| PR-2 | A-002 | EmbeddingGemma-300m backend + `oiw[embeddings]` extra + CI `tfidf` pin | PR-1 |
| PR-3 | A-003/A-004 | CLI `emg status/reindex`, server loads store, promotion persists | PR-1 |
| PR-4 | T0 | `.env.example` tenant keys, `oiw tenant ping`, upload-constraint doc | — (parallel) |
| PR-5 | B-002 | Import parser: callActivity classification; kill skeleton ingest for real sources | — (parallel) |
| PR-6 | B-001/B-003 | Split CodeJam variants, import, Gemma-embed, persist, retrieval fixture | PR-2, PR-3, PR-5 |
| PR-7 | C | `oiw tenant pull` + redact + persist tenant artifacts | PR-3, PR-4 |
| PR-8 | D | Held-out example project + before/after proof YAML | PR-6, PR-7 |
| PR-9 | D-004 | Optional real deploy of held-out package | PR-8, PR-4 |
| PR-10 | E | UI reads persisted store; EMG hit badge truthful; Playwright | PR-8 |

PRs 1–8 are the productization path. PR-10 is the first UI PR allowed.

---

## 12. Developer day-by-day (compressed)

Assume one developer, Gemma weights cached after first download, tenant credentials in hand.

| Day | Work |
|-----|------|
| 1 | PR-1 store. Confirm T0 ping against the tenant in the same afternoon. |
| 2 | PR-2 Gemma embedder. Write the cached-vector paraphrase test. Pin CI to tfidf. |
| 3 | PR-3 load path (CLI + server + promotion). Prove restart persistence with a toy insight. |
| 4–5 | PR-5 parser + PR-6 CodeJam split/import/reindex. Write `wp08-codejam-retrieval.yaml`. |
| 6 | PR-7 pull tenant packages, redact, persist. Stare at import gaps; do not skeletonize. |
| 7 | PR-8 held-out project. Run `--no-emg` vs EMG. Write `wp08-held-out-proof.yaml`. Stop if it fails; fix retrieval or corpus, not the UI. |
| 8 | Only if day 7 passed: optional tenant deploy of the held-out package; then PR-10 UI. |

If the held-out proof fails, the next day is **not** UI. It is either more honest ingest (parser) or a retrieval bug (backend mix, threshold, requirement_to_text too lossy).

---

## 13. Acceptance (work-package level)

WP-08 is done when **all** of the following are true:

### Substrate
- [ ] EMG insights, task nodes, embeddings, and edges survive process restart
- [ ] Store manifest records `gemma` / `google/embeddinggemma-300m` / dim
- [ ] CI uses `tfidf` and does not download Gemma
- [ ] `GET /api/v1/emg/stats` and `oiw emg status` agree after a restart

### CodeJam
- [ ] CodeJam artifacts imported as distinct iFlows with honest import reports
- [ ] No skeleton IR promoted as `sap-codejam`
- [ ] Paraphrase retrieval hits; unrelated requirement does not

### Tenant
- [ ] `OIW_USE_REAL_TENANT=1` lists and downloads real packages
- [ ] At least one tenant artifact persisted with redaction and `provenance.source: tenant`
- [ ] No tenant ZIP committed

### Proof
- [ ] Held-out project is not in the store before the run
- [ ] With-EMG run retrieves a real (codejam or tenant) insight
- [ ] With-EMG run beats `--no-emg` on a documented metric
- [ ] `docs/emg/wp08-held-out-proof.yaml` exists

### UI (last)
- [ ] EMG panel shows the persisted corpus, not an empty state
- [ ] EMG hit badge is truthful
- [ ] Playwright covers non-empty insights + hit badge

---

## 14. Open questions (do not block Track A)

1. **Gemma weights on the developer machine.** First download is ~model-sized. If Hugging Face is blocked, use a pre-cached directory via `HF_HOME` / `SENTENCE_TRANSFORMERS_HOME`. Do not switch the product default back to TF-IDF.
2. **Which tenant package is allowlisted for IR in git?** Default: none. Redacted IR can be committed only with an explicit reviewer decision.
3. **Held-out package name on the tenant.** Human creates it; put the package id in the environment profile, not in code.
4. **Postgres.** After one tenant and a few hundred nodes, if JSONL search is slow, *then* do ADR-010. Not before P4.

---

## 15. Key files the developer will touch

| Area | Path |
|------|------|
| Embeddings | `apps/cli/oiw/emg/embedding.py`, `apps/cli/pyproject.toml` |
| New store | `apps/cli/oiw/emg/store.py` (new), `task_store.py`, `edge_store.py`, `promotion.py` |
| Retriever wiring | `apps/cli/oiw/emg/retrieval.py`, `apps/cli/oiw/agent/orchestrator.py` |
| CLI | `apps/cli/oiw/cli.py` (`emg status/reindex`, `tenant ping/pull`) |
| Tenant | `apps/cli/oiw/tenant/sap_ci_adapter.py`, `credentials.py`, `__init__.py` |
| Import | `apps/cli/oiw/compiler/sap_import.py`, `sap_flow_parser.py` |
| Ingest | `packages/seed-corpus/real_ingestion.py`, `promote.py`, `cross_task_pipeline.py` |
| API | `apps/server-python-prototype/oiw_server/routes/emg.py`, `main.py` |
| UI (Track E only) | `apps/web/src/components/emg/*`, `apps/web/src/App.tsx` |
| Proof | `docs/emg/wp08-codejam-retrieval.yaml`, `docs/emg/wp08-held-out-proof.yaml`, `examples/held-out-*/` |
