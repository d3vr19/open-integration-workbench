# Hands-Free Roadmap: Real EMG → Autonomous Artifact → Tenant Upload

> **Status:** ACTIVE — governing plan for the d3vr19 fork.
> **Origin:** Approved 2026-08-25. This document is the anti-drift anchor: every
> PR must state which phase (and sub-phase) it advances, and deviations must be
> recorded here before code lands.
> **End goal:** requirement in → agent builds an iFlow autonomously inside a fast
> local simulated world (reward = functional iFlow) → one human approval →
> upload + deploy + verify against a live BTP tenant.

## 0. Why this plan exists

Three gaps separate today's tree from that end state:

1. **EMG is not real.** `google/embeddinggemma-300m` weights may sit in the local
   HF cache, but without `sentence-transformers` installed,
   `GemmaEmbedder.embed()` silently degrades to a hash pseudo-embedding
   (`apps/cli/oiw/emg/embedding.py`, the `except Exception` fallback). Learning
   on TF-IDF / pseudo vectors is garbage-in for the whole learning loop.
2. **Upload is impossible — twice over.** By policy
   (WP-08 §C-004), all tenant write ops raise `NotImplementedError`
   (`apps/cli/oiw/tenant/sap_ci_adapter.py`). And independently, `oiw build`
   emits OIW-IR directories — there is **no IR→CPI designtime exporter**, so
   even with write ops implemented there would be nothing CPI-uploadable.
3. **The simulated world is too shallow to be a reward environment.** Steps
   simulate semantics but do not execute payloads; `oiw deploy upload` sends a
   fake 20-byte archive; `deploy verify` is an unconditional stub.

## 1. Policy constraints carried forward (non-negotiable)

These come from WP-08 and the threat model; every phase below operates inside them:

- The tenant is a library, not a scratchpad. Writes go to a **pre-created,
  human-owned scratch package only** (update-only per T0-003/D-004).
- `OIW_USE_REAL_TENANT=1` must NEVER be set in CI. Live-tenant tests are
  manually gated via env-var skip conditions.
- Credentials live in env vars only (`OIW_TENANT_*`, `OIW_CRED_<REF>_*`);
  never in files, never in LLM context.
- Human approval gate stays between PROPOSED→APPROVED for anything touching
  the tenant. "Turbo" autonomy applies **only inside the local simulated
  world** (Phase 5d), which is hard-bounded: no tenant adapter calls from
  autonomous mode, token/wall-clock/iteration caps, all trajectories recorded.
- CI keeps `OIW_EMBEDDING_BACKEND=tfidf`; real-model work never becomes a
  CI dependency.

## 2. Phases

### Phase 0 — Fork & baseline (½ day)

- [x] Fork under `d3vr19`; remotes `origin=d3vr19/…`, `upstream=hehenaice/…`.
- [x] Python 3.12 venv (uv-managed) — local Arch system Python is 3.14;
      torch support there is not dependable, CI uses 3.12.
- [x] Baseline proof on the fork: all four pytest suites (cli, server,
      mcp-server, gateway) + seed-corpus suite + ruff + SPA build green.
      Record results in this file before any functional change.

**Baseline results (2026-08-25, CPython 3.12.14 via uv):**

| Suite | Result |
|---|---|
| `apps/cli` pytest | 381 passed, 6 skipped |
| `apps/server-python-prototype` pytest (`OIW_WORKSPACE=examples`) | 87 passed |
| `apps/mcp-server` pytest | 20 passed |
| `services/model-gateway-python` pytest | 43 passed |
| `packages/seed-corpus` pytest | 132 passed |
| ruff check + format (CI scope: apps/cli, server, mcp-server, gateway) | clean |
| SPA build (`tsc -b && vite build`) | ✓ 391 kB bundle |

Note: ruff reports 59 pre-existing E402s under `packages/seed-corpus/`
(sys.path-insert idiom); out of CI lint scope by upstream design — do not
"fix" opportunistically, it would poison diffs against upstream.

### Phase 1 — Real embeddings, loudly (OW-033) *(2–3 days)*

1. [x] Install `oiw[embeddings]` (sentence-transformers 5.x + torch 2.13 CPU) into the 3.12 venv.
2. [x] Point `OIW_EMBEDDING_MODEL` at the cached model (`unsloth/embeddinggemma-300m`).
3. [x] **Kill the silent fallback**: new `OIW_EMBEDDING_STRICT=1` mode makes
   `embed()` raise instead of pseudo-degrading; `oiw emg status` gained
   honest fields (`backendUsable`, mismatch counts); learning paths refuse
   fake vectors (see "honesty seams fixed" below).
4. [x] Reindexed the CodeJam store to `gemma / unsloth/embeddinggemma-300m / dim=768`
   — `Vectors verified against manifest: OK`, 0 mismatches.
5. [x] **Acceptance evidence** (see progress log for numbers): paraphrase
   separation 0.851 vs 0.693; held-out gate re-PASSED with real-vector
   retrieval probe at similarity **0.4831** (TF-IDF control query: 0.0000 —
   dim-mismatch guard proves backends are never mixed).
6. [x] CI untouched (TF-IDF).

**Honesty seams fixed during this phase (all found by reading the code, not
by trusting docs):**

| Seam | Before | After |
|---|---|---|
| `GemmaEmbedder.embed()` | silent hash-pseudo fallback | raises under `OIW_EMBEDDING_STRICT`; else records `last_embed_pseudo` |
| `emg reindex` (cli.py) | hardcoded TF-IDF embedder while stamping ANY manifest backend | builds the real backend, canary-embeds before wiping anything, stamps resolved backend/model/dim from the embedder instance |
| `build_emg_store` | env backend ignored; always TF-IDF embedder | constructs the declared backend or fails loudly |
| `EMGRetriever` | hardcoded TF-IDF query embedder | explicit arg > env backend (loud failure) > TF-IDF default |
| `oiw emg status` | parroted the manifest | probes actual usability + reports vector/dim mismatches |
| seed-corpus task nodes | indexed `confidentialityScope: project` → invisible to all cross-project retrieval | ingested as `organization` scope (public Apache-2.0 material); reindex preserves per-node scope/approval |

### Phase 2 — UI reads the real store (OW-032 / WP-08 PR-10) *(~2 days)*

Server groundwork exists (startup load + enriched `/emg/stats`). Remaining:

1. [x] Agent routes (`oiw_server/routes/agent.py`) return a truthful `emg`
   block (`used`/`confidence`/`insightId`/`taskId`/`provenance`) on both
   plan and implement responses. `None` when no durable store is loaded,
   so the UI can distinguish "fresh workspace" from "no hit". Retrieval
   normalization uses the CLI's deterministic interpreter for component
   parity with corpus building.
2. [x] Web: EMG types live in `api.ts`; `EmgInsightPanel` renders the
   enriched stats chip (`backend·dim ✓/⚠`); truthful ⚡ badge threaded
   CoPilotPanel→App via an `onEmgHit` callback — the hardcoded
   `emgUsed={false}` is gone.
3. [x] Finished `TrajectoryViewer` (was an unimported stub): fetches
   `GET /emg/insights/{id}`, renders expert workflow steps + corrections.
4. [x] Added missing CSS for `.insight-card*` / `.pattern-browser*` /
   `.trajectory-viewer*`.
5. [x] Playwright e2e (`emg-insights.spec.ts`): panel counts must equal
   API truth; badge visibility must equal the server's `emg.used` claim.
   Verified green in BOTH scenarios: fresh empty workspace AND a
   gemma-seeded 7-insight store (where the incompatible-backend chip
   correctly shows ⚠ because the server process ran with TF-IDF env).

### Phase 3 — Tenant update-only write path (OW-031 / WP-08 PR-9, D-004) *(3–4 days)*

Per WP-06 §7 sketch:

1. [x] Implement `SapCiTenantAdapter.upload_package`
   (PUT `/IntegrationDesigntimeArtifacts(Id='{id}',Version='{ver}')/$value`),
   `deploy` (POST `/IntegrationRuntimeArtifacts`), `poll_deployment`
   (GET poll endpoint), `get_runtime_logs` (MessageProcessingLogs).
   CSRF token fetched opportunistically (`X-CSRF-Token: fetch`) and
   attached when the tenant issues one.
2. [x] **Policy guards**: writable-package allowlist (`OIW_TENANT_WRITABLE_PACKAGES`
   / `writable_packages=`; empty = read-only, every write refused loudly
   BEFORE any network call), update-only target resolution (an empty
   package is refused with remediation per T0-003), drift-check-before-upload,
   APPROVED state-machine gate, and enforcement of
   `deploymentPolicy.approvers` membership + approval TTL at upload time.
3. [x] Fixed CLI seams: `deploy upload|execute|check-drift|verify` use
   `build_tenant_adapter()` (mocks keep their durable state dir via a new
   factory passthrough); upload sends real dist/ ZIP bytes + recomputed
   sha256 (was: literal `b"mock-build-artifact"`); check-drift auto-computes
   the local digest from the real build output (was: `"sha256:auto-computed"`).
4. [x] Tests: 9 new MockTransport tests following test_tenant.py
   conventions (allowlist refusals, PUT payload/CSRF assertions, deploy
   POST shape, poll mapping, MPL parsing); rewrote the write-ops-guard
   test from NotImplementedError to allowlist semantics.
5. [ ] Live de-risk probe + smoke against **AdequareGST** (user-designated
   scratch package) — manual, operator-run:
   ```
   export OIW_USE_REAL_TENANT=1 OIW_TENANT_URL=... OIW_TENANT_USER=... OIW_TENANT_PASSWORD=...
   export OIW_TENANT_WRITABLE_PACKAGES=AdequareGST
   oiw tenant list --top 50                      # confirm AdequareGST visible
   oiw tenant artifacts --package AdequareGST    # needs ≥ 1 existing artifact (update-only)
   cd examples/held-out-order-async && oiw build --target sap-cloud-integration-2026-07
   oiw deploy propose --profile btp --package AdequareGST
   oiw deploy approve --profile btp --package AdequareGST --approver <you>
   oiw deploy upload --profile btp --package AdequareGST
   oiw deploy execute --profile btp --package AdequareGST
   oiw deploy verify --profile btp --package AdequareGST
   ```
6. [ ] Live smoke results recorded here.

### Phase 4 — CPI bundle exporter *(the hidden blocker, 4–5 days)*

Without this, "upload the integration" cannot happen regardless of Phase 3:

1. IR→designtime-ZIP writer: BPMN2/iflw serialization (inverse of
   `parse_bpmn2_iflw`, reusing `_ACTIVITY_TYPE_MAP` inverted),
   `parameters.prop` (+ `.propdef`), `META-INF/MANIFEST.MF`, `.project`.
   Archive shapes proven by `packages/test-fixtures/real-sap/*`.
2. Golden round-trip fixtures extended: IR → export ZIP → re-import →
   identical IR; determinism double-build check extended to the ZIP output.
3. `oiw build --format cpi-designtime-zip`.

### Phase 5 — The simulated world ("virtual organism") *(the big layer — staged)*

Design translation of the reward-environment concept onto OIW's existing bones.
Each sub-phase lands independently; nothing else blocks on Phase 5 except
Phase 6's demo quality.

- **5a. Message-execution engine** — payloads actually flow through the graph:
  Groovy executes via the JVM sandbox bridge (`services/runtime-worker-jvm`,
  SecureASTCustomizer sandbox), XSLT via lxml, converters/routers/filters run
  real logic; MPL-style structured logs; realistic error propagation.
  Fidelity labels upgrade honestly (`simulated` → `compatible-subset`) per
  component, never overclaimed.
- **5b. World dynamics** — mock HTTP receiver server, fake SFTP endpoint,
  fault injection (timeouts, 500s, malformed payloads, schema drift). The
  environment the organism lives in.
- **5c. Reward function v1** — FlowTest pass/fail + execution telemetry feed
  the existing 9-dim reward vector (`apps/cli/oiw/emg/reward.py`); failures
  auto-capture as learning sessions so the EMG grows from every run.
  Functional iFlow = reward.
- **5d. Turbo loop** — `oiw agent --turbo`: plan→implement→simulate→repair
  cycles with no per-step approval pauses, hard-bounded as specified in §1.
  Human gate remains at PROPOSED→APPROVED before any tenant interaction.

### Phase 6 — Hands-free end-to-end proof *(~2 days)*

`REQUIREMENT.md → turbo agent → artifact built & green in sim → drift check →
single human approval → upload+deploy to scratch package → poll DEPLOYED →
log verify → trajectory promoted to EMG insight`.

Demo script + captured transcript in `docs/plans/`, DEVELOPMENT_LOG entry,
README status update.

## 3. Sequencing & dependencies

```
P0 ──► P1 (real embeddings) ──► P2 (UI reads store) ──► WP-08 closed
 │
 ├──► P3 (write path) ──► P4 (exporter) ──► P6 (E2E demo)
 │              ▲                ▲
 └──► P5a/b/c/d (sim world) ────┘   (P5 can start after P0; independent of P3/P4)
```

| Phase | Unlocks | Est. |
|---|---|---|
| 0 | Everything | ½ d |
| 1 | Trustworthy EMG | 2–3 d |
| 2 | Visible EMG; WP-08 fully closed | ~2 d |
| 3 | Deploy capability | 3–4 d |
| 4 | Uploadable artifacts | 4–5 d |
| 5 | The organism | open-ended, staged |
| 6 | End-goal demonstrated | ~2 d |

## 4. Risks & mitigations

| Risk | Mitigation |
|---|---|
| torch on Arch/Python 3.14 instability | uv-managed CPython 3.12 venv dedicated to OIW |
| PUT $value payload shape unknown | Phase 3 step 5 probe before exporter work depends on it |
| Gemma license (Gemma terms, not Apache-2.0) | Already handled repo-wide: weights never vendored, download-at-first-use, CI exempt |
| Phase 5 scope creep | Sub-phases land independently; each must keep CI green; fidelity labels never overclaimed |
| Fork/upstream drift | Weekly `git fetch upstream`; DEVELOPMENT_LOG.md merge conflicts resolved in favor of upstream then re-append |

## 5. Progress log

Append-only. Newest first. Format: `(date) phase.step — what happened, evidence link`.

- 2026-08-25 — P0.0 — Plan ratified; fork `d3vr19/open-integration-workbench`
  created; remotes wired (`origin`=fork, `upstream`=hehenaice); branch
  `plans/hands-free-roadmap` opened with this document.
- 2026-08-25 — P0 complete — uv-managed CPython 3.12.14 venv at `.venv/`;
  all editable installs; baseline green (see table above). Fork PR #1 open
  for visibility. Starting Phase 1 (real embeddings).
- 2026-08-25 — P1 complete — Real EmbeddingGemma-300m (cached
  `unsloth/embeddinggemma-300m`, offline) now powers the EMG:
  - Six honesty seams fixed (table above); 24 new tests, CLI suite 400 passed.
  - Paraphrase separation: 0.851 related vs 0.693 unrelated (real vectors).
  - Held-out gate re-run under gemma/768: **PASS** — mechanics-first hit
    intact; new vector-retrieval probe: best match 0.4831 with the store's
    own backend vs 0.0000 for a TF-IDF control query (dim-mismatch guard).
    Proof regenerated at `docs/emg/wp08-held-out-proof.yaml`
    (`embeddingRetrievalProbe` section).
  - Found + fixed a latent confidentiality bug while proving retrieval:
    seed-corpus task nodes were indexed project-private, making them
    unreachable by cross-project search — the "real embeddings" proof would
    have silently read zero rows without this fix.
  - Dev env contract: `OIW_EMBEDDING_BACKEND=gemma`,
    `OIW_EMBEDDING_MODEL=unsloth/embeddinggemma-300m`, `OIW_EMBEDDING_DIM=768`,
    `OIW_EMBEDDING_STRICT=1` for any real learning work.
- 2026-08-25 — P2 complete — Truthful EMG end-to-end (commit bde8b85,
  branch wp08/pr10-emg-ui): agent routes report real retrieval results;
  ⚡ badge driven by server metadata; TrajectoryViewer finished; honesty
  chips (backend·dim·compatible) in the panel; 2 new Playwright tests
  proving UI==API truth in empty + seeded scenarios. Process note: branch
  was initially cut from a stale local main (pre-P1) — caught because the
  new EMGRetriever embedder param "disappeared"; fixed by resetting onto
  origin/main. Lesson recorded: always branch from origin/main, never
  local main, on this fork.
- 2026-08-25 — P3 code complete (branch wp08/pr9-write-path) — update-only
  write path landed: adapter write ops with CSRF + allowlist gating,
  deploy CLI seams fixed (real bytes/digest/verify), approval approvers +
  TTL enforcement, 9 new MockTransport tests, CLI suite 414 passed.
  Scratch package designated by operator: **AdequareGST**. Live smoke
  pending credentials in env.
- 2026-08-25 — P3 LIVE SMOKE (partial PASS) + P4 exporter MVP live-proven —
  against AdaequareGST/open_mateo_test with operator credentials:
  - VERB DISCOVERIES (all live-proven, sketch was wrong): PUT $value=501;
    multipart=501; POST entity=CREATE-only (existing id ⇒ misleading 500);
    **UPDATE = PUT /IntegrationDesigntimeArtifacts(Id,V) {ArtifactContent:b64}**,
    which rejects Bundle-SymbolicName changes (HTTP 400) — exporter now
    inherits identity from the downloaded current bundle.
  - Winning bundle shape (1826 bytes, HTTP 200): minimal MANIFEST.MF with
    `Bundle-SymbolicName: <id>;singleton:=true`, `.project` without buildSpec,
    `metainfo.prop` (NOT parameters.prop), our generated .iflw — SAP's parser
    accepted OIW-generated BPMN2 verbatim.
  - `oiw deploy upload --format cpi`: propose→approve→upload ALL GREEN via
    CLI; artifact content replaced on the live tenant.
  - OPEN: activation. /IntegrationRuntimeArtifacts is a read-only view
    (GET ok, POST=405). The deploy-activate verb needs discovery (SAP docs
    or devtools capture of a manual UI deploy). verify() polls that entity
    once activation lands.
