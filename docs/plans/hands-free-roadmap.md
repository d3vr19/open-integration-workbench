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

1. Install `oiw[embeddings]` (sentence-transformers + CPU torch) into the 3.12 venv.
2. Point `OIW_EMBEDDING_MODEL` at the cached model (`unsloth/embeddinggemma-300m`)
   or pre-fetch `google/embeddinggemma-300m` so backend/model/dim stamps match
   documented defaults exactly.
3. **Kill the silent fallback**: new `OIW_EMBEDDING_STRICT=1` mode makes
   `embed()` raise instead of pseudo-degrading; `oiw emg status` gains an
   honest real-vs-pseudo field; learning-session commands refuse non-real
   backends unless explicitly overridden (new DEV registry entry documenting
   the behavior change).
4. `oiw emg reindex --backend gemma --dim 768` — idempotent; dim-mismatch
   protection handles migration of existing store content.
5. **Acceptance test**: re-run the held-out proof
   (`docs/emg/wp08-held-out-proof.yaml`, was similarity 0.35 under pseudo
   embeddings) and the CodeJam retrieval proof with real embeddings. Numbers
   must measurably improve or at minimum hold; record before/after here and
   in DEVELOPMENT_LOG.md.
6. CI untouched (TF-IDF).

### Phase 2 — UI reads the real store (OW-032 / WP-08 PR-10) *(~2 days)*

Server groundwork exists (startup load + enriched `/emg/stats`). Remaining:

1. Agent routes (`oiw_server/routes/agent.py`) return `emgUsed` /
   retrieval-hit metadata in `PlanResponse`/`ImplementResponse`. Today they
   carry zero EMG references, which forces the hardcoded
   `emgUsed={false}` in `App.tsx`.
2. Web: EMG types move into `api.ts`; `EmgInsightPanel` renders the enriched
   stats chip (`embeddingBackend · dim · compatible ✓`); truthful ⚡ badge
   threaded CoPilotPanel→App.
3. Finish `TrajectoryViewer` (currently an unimported stub) using
   `GET /emg/insights/{id}`.
4. Add missing CSS for `.insight-card*` / `.pattern-browser*`.
5. Playwright e2e: non-empty insights panel + hit-badge truthfulness
   (per OW-032 acceptance definition).

### Phase 3 — Tenant update-only write path (OW-031 / WP-08 PR-9, D-004) *(3–4 days)*

Per WP-06 §7 sketch:

1. Implement `SapCiTenantAdapter.upload_package`
   (PUT `/IntegrationDesigntimeArtifacts(Id='{id}',Version='{ver}')/$value`),
   `deploy` (POST `/api/v1/IntegrationRuntimeArtifacts`), `poll_deployment`
   (GET poll endpoint), `get_runtime_logs` (MessageProcessingLogs).
2. **Policy guards**: target-package allowlist (scratch package id only),
   mandatory drift-check-before-upload, APPROVED state-machine gate, and
   actual enforcement of `deploymentPolicy.approvers` + approval TTL
   (specified since WP-05, never implemented).
3. Fix CLI seams: `deploy upload|execute|check-drift` use
   `build_tenant_adapter()` instead of hardcoded mocks; upload sends real
   `dist/` bytes + recomputed sha256; `verify` polls real status/logs.
4. Tests: `httpx.MockTransport` injection following
   `apps/cli/tests/test_tenant.py` conventions; rewrite the
   write-ops-guard test; add `@pytest.mark.skipif(not os.environ.get("OIW_TENANT_URL"))`
   live-test class (manual only).
5. Early de-risk probe: PUT payload-shape verification against the scratch
   package before building the Phase 4 exporter around it.
6. Live smoke: held-out example uploaded/deployed/verified against the scratch
   package (manual, operator-run).

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
