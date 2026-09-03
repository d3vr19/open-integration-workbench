# Work Package WP-09: Frontend Engineering Track — SPA Decomposition, Trace Viewer v1.5, E2E Hardening

**Phase:** Frontend productization of the Visual Workbench (Phase 2 completion + Phase T continuation)
**Prerequisite:** WP-08 Track D gate PASSED (2026-08-19) — UI work is authorized (`docs/emg/wp08-held-out-proof.yaml`)
**Spec sections:** §10 (Visual Designer), §12.3 (Interaction Modes), §21 (REST API), §16.2 (local security posture)
**Branch convention:** `feature/wp09-<track>-<task>` (e.g. `feature/wp09-a-002`)
**Owner:** Frontend engineer (new onboard). Backend/agent engineer remains owner of everything outside `apps/web`.
**Gate:** Track D (experiment-engine UI) is **out of scope until the backend B2 engine lands**. Do not start it early.

---

## 1. Objective

The UI's honesty layer is done (PR-10, commit `bde8b85`: truthful EMG metadata end-to-end, ⚡ badge driven by server truth, 2 Playwright specs in CI). What remains is **fluidity and depth**: finish the SPA decomposition (OW-029), replace the hand-written API client with a generated one (OW-015), ship trace viewer v1.5 (the roadmap's open thread #1), and grow E2E coverage toward the 10 critical journeys (OW-012) — all without regressing the truthfulness contracts or the 12 required CI checks.

This package also defines **how the frontend engineer works alongside the backend engineer** (Section 2) so that two people can mutate the same repository concurrently without breaking each other. That section is not optional reading.

---

## 2. Collaboration protocol (how to not break stuff)

The backend engineer is concurrently building B2 (Experiment Engine: `oiw experiment`, law registry, new API routes) and the Phase B piece backlog (Mapping, splitter, ProcessCall). His work is **additive to the API surface**; yours is **additive to `apps/web`**. Follow the matrix below and the two tracks cannot collide.

### 2.1 Ownership matrix

| Area | You own | Rules |
|------|---------|-------|
| `apps/web/src/**`, `apps/web/e2e/**`, `apps/web/index.html`, CSS | ✅ Full ownership | Free to refactor; keep Playwright green |
| `apps/web/vite.config.ts`, `tsconfig*.json`, `package.json` (deps) | ✅ with coordination | **Major version bumps (React, React Flow, Vite, TS) need a heads-up first.** Note: README says "React Flow 12" but `package.json` pins `reactflow ^11` — do not "fix" this unilaterally; it's a doc-vs-code divergence to resolve in your first PR (A-001). |
| `apps/web/playwright.config.ts` | ✅ | Do not change `workers: 1` / serial mode — tests mutate shared workspace state |
| `packages/api-spec/openapi.yaml` | ⚠️ Shared contract | You may add response fields/types you need **as a proposal**, but the backend engineer merges changes to server behavior. The spec is the contract; the server is his. |
| Server Python (`apps/server-python-prototype/**`), CLI (`apps/cli/**`), compiler, tenant adapter | ❌ Never edit | If the UI needs a new endpoint or a payload change: **file an issue (feature template), tag it `api-request`**. Backend implements, then you consume via the generated client. Never patch server Python to unblock a UI task. |
| CI workflows (`.github/workflows/**`) | ❌ Backend owns | Your PRs must simply keep them green. If a frontend job needs a change (e.g. oxlint step), request it. |
| `DEVELOPMENT_LOG.md` | ⚠️ Append-only, everyone | Every PR appends an entry. Never rewrite history — supersede with a note. |
| `.oiw/**`, `.env`, tenant anything | ❌ Never touch, never run | See 2.4. |

### 2.2 Branch and PR discipline

- **Cut branches from `origin/main`, never local `main`.** Recorded incident (2026-08-25): a WP-08 branch cut from stale local main silently lost an `EMGRetriever` parameter and cost a debugging session. `git fetch origin && git checkout -b feature/wp09-a-002 origin/main`.
- One PR per task (Section 7 table). Small and mergeable beats large and heroic.
- Commit convention (spec §11.3): `feat(ui): ...`, `fix(ui): ...`, `refactor(ui): ...`, `test(ui): ...`, `docs(ui): ...`.
- Every PR description states: which WP-09 task it advances, the checks run locally, and the log entry (or a promise to append it in the same PR).

### 2.3 Checks that must be green before you push (every PR, no exceptions)

```bash
cd apps/web
npx tsc -p tsconfig.app.json --noEmit   # type-check (CI runs exactly this)
npm run lint                            # oxlint
npm run build                           # tsc -b && vite build
npx playwright test                     # both spec files, against fixture workspace (Section 3)
```

The backend engineer additionally runs the Python suites (CLI/Server/MCP/Gateway) on every merge to main — but if you touched nothing outside `apps/web`, those are not affected. Keep it that way.

### 2.4 Hard safety rules (things that have cost blood or secrets)

1. **Never point tests or dev servers at the repository's own `.oiw/` state.** `.oiw/emg/` holds the live 602-insight Gemma store (600 absorbed tenant flows). It was destroyed once by a bad reindex (rebuilt losslessly, regression-tested since — but you are not the person to re-learn that lesson). Always run with `OIW_WORKSPACE` pointing at a **fixture copy** (Section 4).
2. **Never run tenant commands** (`oiw tenant ...`, `oiw emg reindex`, `oiw agent --turbo`, `oiw deploy ...`). You have no credentials and need none. Every UI task is satisfiable against the fixture workspace. If a UI feature genuinely requires tenant data to be demonstrated, that's an `api-request` issue (e.g. B-003 serves *cached, gitignored* calibration YAML via a read-only route — backend's job to expose).
3. **Never commit `.env`, tenant URLs, playwright-report/, test-results/, dist/, node_modules/.** gitleaks runs in CI and blocks. The `.gitignore` already covers these — don't `git add -f` your way around it.
4. **The EMG badge is a truthfulness contract, not a decoration.** `data-testid="emg-hit-badge"` renders iff the server's `emg.used === true` (asserted by `emg-insights.spec.ts` in both empty and seeded scenarios). Any refactor of `EmgInsightPanel`/`CoPilotPanel` that hardcodes, guesses, or cosmetically fakes retrieval state is a **regression of the project's honesty floor** — worse than a crash. Same for the honesty chips (backend · dim · compatible ⚠).
5. **Never rewrite `DEVELOPMENT_LOG.md` history.** Append at the bottom. It is the single source of truth; the log's own header is the law.

### 2.5 How to request API changes

1. File a GitHub issue using the feature template, label `api-request`, include: the UI need, a proposed OpenAPI snippet, and which WP-09 task blocks on it.
2. Backend engineer implements server + spec update + tests, appends log entry.
3. You regenerate the client (A-002 tooling) and consume.
Current known example: **B-003** (tenant-MPL comparison) needs a read-only route serving the cached calibration rows (`.oiw/calibration-*.yaml`). It is the only Track B task with a backend dependency — plan it last.

---

## 3. Honest diagnosis (what the UI actually is today)

| Area | Reality | Task |
|------|---------|------|
| EMG truthfulness | **DONE** (`bde8b85`): panel reads persisted store; badge + chips driven by server metadata; 2 Playwright specs prove UI==API truth in empty + seeded scenarios | Protect, don't redo (rule 2.4-4) |
| `App.tsx` | 569-line god component. Canvas/palette/properties/co-pilot/EMG/deploy/trace components are extracted; the **data-loading + pending-ops machine** still lives in `App` | A-003 |
| `api.ts` | 350-line hand-written fetch client; the OpenAPI spec (`packages/api-spec/openapi.yaml`) exists and is maintained | A-002 (OW-015) |
| Trace viewer | **v1 shipped** (commit `156b508`): engine snapshots per-step body/headers/properties/duration/exception; `TraceInspector.tsx` shows per-step chips with click-to-inspect; raw-event toggle. Open v1.5 threads: canvas node badges → inspector, replay/step-through, tenant-MPL comparison | B-001..B-003 |
| E2E | `copilot.spec.ts` (2 tests) + `emg-insights.spec.ts` run in CI via `e2e.yaml` (Python server on :8000, Vite on :5173, git-init'd copy of `examples/order-to-s4`). **README's "What's not yet implemented" still claims Playwright E2E isn't wired into CI — that's stale.** | A-001 (truth fix), C-001 (OW-012 growth) |
| Docs drift | `apps/web/README.md` says "Vite 6 / React Flow 12 / Zustand planned"; package.json has Vite 8, `reactflow ^11`, no Zustand | A-001 |
| Styling | Tailwind 4 via `@tailwindcss/vite`; class-name conventions like `.emg-panel__header` (BEM-ish) in `App.css` | Match existing conventions |

---

## 4. Environment bootstrap (your first hour)

You need Python **only to run the API server** — you will not write Python. Node 22 + npm for everything else. No Docker, no tenant, no LLM keys, no `.env`.

```bash
git clone https://github.com/d3vr19/open-integration-workbench.git   # or the hehenaice upstream per your fork setup
cd open-integration-workbench
python -m venv .venv && source .venv/bin/activate
pip install -e apps/cli -e apps/server-python-prototype

# Fixture workspace — NEVER the repo's own examples/ dir (it would write .oiw state next to the live store)
mkdir -p /tmp/oiw-ui-workspace
cp -r examples/order-to-s4 /tmp/oiw-ui-workspace/
cd /tmp/oiw-ui-workspace/order-to-s4 && git init -q && git add . && \
  git -c user.email=ui@local -c user.name=ui commit -q -m "fixture"   # baseRevision validation requires git

cd -   # back to repo root

# Terminal 1 — API server (binds 127.0.0.1; no auth in local mode, spec §16.2)
OIW_WORKSPACE=/tmp/oiw-ui-workspace uvicorn oiw_server.main:app --port 8000

# Terminal 2 — SPA (vite proxies /api -> :8000)
cd apps/web && npm ci && npm run dev    # http://localhost:5173

# Terminal 3 — E2E (playwright.config.ts starts its own vite; server above must be running)
npx playwright test
```

If all 4 E2E tests pass locally, your environment is correct. If `emg-insights.spec.ts` fails with empty-store assertions, you pointed `OIW_WORKSPACE` at the wrong directory.

---

## 5. Tracks

### Track A — Foundations (start here)

**A-001: Documentation truth sweep (your first PR — deliberately tiny).**
- Fix `apps/web/README.md` stack table (Vite 8 not 6; `reactflow ^11` vs "React Flow 12" — pick the code's side, note the divergence, or coordinate an upgrade; state-management row: "React hooks, no Zustand").
- Fix root `README.md` line claiming "Playwright E2E in CI (OW-026 — tests pass locally, not yet wired into GitHub Actions)" — stale; `e2e.yaml` runs both specs. Move OW-026 out of "not yet implemented".
- Append your first log entry. Purpose of this PR: you learn the log law, the commit convention, and the PR pipeline on a zero-risk change.

**A-002: Generated TypeScript API client (OW-015).**
- Replace hand-written `apps/web/src/api.ts` with a client generated from `packages/api-spec/openapi.yaml` (openapi-typescript + a thin fetch wrapper, or equivalent — your call, propose in the PR).
- Keep the module's public surface (`api.listProjects()` etc.) stable so component churn is minimal; adapt at the boundary, not in every component.
- Wire generation into `package.json` scripts (`npm run api:gen`) so spec updates become mechanical. Document in `apps/web/README.md`.
- The e2e suite must stay green with zero test edits — it is your regression net.

**A-003: SPA decomposition + fluidity (OW-029 / WP-08 E-002 — the flagship).**
- Extract the data-loading and pending-ops state machine from `App.tsx` into hooks/stores per the README's plan (Zustand *may* be introduced here — that IS the coordination-worthy dep change; announce it).
- Per-panel loading and error states — **no single global `error` banner**.
- Pending ops: optimistic local state with a single PATCH on Save (E-002's explicit design). If whole-flow reload on palette drop still exists anywhere, fix it.
- Constraint: `App.tsx` was 552 lines at WP-08 diagnosis and is 569 today. Target: `App.tsx` < ~150 lines of pure layout by the end of this task. Ship it as a **series** of small PRs (e.g. useProjectData, useFlowEditor, useSimulation), each keeping Playwright + tsc green — not one big-bang rewrite.
- Do NOT touch the `data-testid` contracts: `emg-hit-badge`, `emg-hit-details`, the sidebar section selectors used by e2e (`sidebar__section:has(.sidebar__title:has-text("Projects"))`). If a refactor must change a selector, update the spec in the same PR and say so.

### Track B — Trace viewer v1.5 (roadmap open thread #1)

**B-001: Canvas node badges wired to the inspector.**
- During/after a simulation, React Flow nodes get pass/fail/duration badges derived from the trace payload; clicking a badge selects that step in `TraceInspector`. The trace data is already fully streamed (`/ws/trace` + simulate API carry per-step snapshots) — this is pure frontend wiring in `FlowCanvas.tsx` / `TraceInspector.tsx` / `App.tsx` state.

**B-002: Replay/step-through mode.**
- A transport control in the trace panel: step forward/back through the recorded trace, showing the exchange snapshot at each step (bodies/headers/properties are already in the payload). No server changes.

**B-003: Tenant-MPL comparison view (backend-gated — plan last).**
- Local trace vs cached calibration rows (MessageProcessingLogs) side by side — "parity's face" per the roadmap.
- **Requires an `api-request`** (Section 2.5): read-only route serving `.oiw/calibration-*.yaml` from the *dev* workspace, never from CI. File the issue early; work B-001/B-002 while it cooks.

### Track C — E2E hardening (OW-012, continuous)

**C-001: Grow the journey suite toward the 10 critical journeys.**
- Existing: co-pilot suggest+apply / reject plan; EMG panel counts + badge truthfulness. Next candidates, in order: (3) drag-and-drop a palette step → save → reload → node persisted; (4) validate button shows real validation errors on a known-bad flow (fixture: any `tests/` negative case); (5) simulate → trace inspector shows per-step entries; (6) diff viewer renders a structured diff after a node config edit; (7) dirty-state indicator + Save → PATCH round-trip.
- Discipline (non-negotiable): serial mode, single worker, shared mutating workspace — clean up what you mutate or assert on state your test created; never assume fixture freshness.
- Each new spec keeps the invariant: **UI display == API truth**. Fetch the API in the test and assert against it, don't hardcode counts (see how `emg-insights.spec.ts` does it).

### Track D — Experiment Engine views (GATED — do not start)

B2 (`oiw experiment`, law registry, verdict-ladder UI surface) is the backend engineer's current existential deliverable. When it lands it will grow the API additively (experiment status, law registry listing). A read-only "Experiments / Laws" panel is a natural follow-on WP. **Out of scope for WP-09.** Watch `packages/api-spec/openapi.yaml` growth as your signal.

---

## 6. What not to do

| Temptation | Why not |
|------------|---------|
| Point `OIW_WORKSPACE` at the repo root or `examples/` for tests | Writes `.oiw` state next to the live 602-insight EMG store. Fixture copy in `/tmp` only. |
| Run `oiw emg reindex`, `oiw tenant ...`, `oiw agent ...`, `oiw deploy ...` | Live-state and/or tenant operations. Not yours, not needed, and the reindex has a destruction history. |
| Edit `apps/cli/**` or server Python to unblock a UI need | Breaks the ownership boundary. File an `api-request` issue (Section 2.5). |
| Hardcode the EMG badge / counts / confidence anywhere | Regresses PR-10's truthfulness contract — the e2e specs exist precisely to catch this. |
| Hardcode expected counts in Playwright tests | Assert against live API responses (UI == API truth, not UI == magic number). |
| Big-bang rewrite of `App.tsx` in one PR | Unreviewable, and it invalidates the e2e net mid-flight. Series of small extractions. |
| Cut branches from local `main` | Stale-main incident is in the log (2026-08-25). `origin/main` always. |
| Major dep bumps (React 19.x→20, reactflow 11→12, Vite major) without coordination | These are the project's load-bearing versions; the backend also builds the SPA in CI and a surprise break stalls both of you. |
| Change Playwright to parallel workers to "speed it up" | Tests mutate a shared workspace; parallelism corrupts fixtures. |
| Pixel-copy SAP's CPI UI | Legally forbidden (ADR-002). Familiar terminology yes; pixel-identical no. |
| Commit `.env`, tenant URLs, customer artifacts, `dist/`, `playwright-report/` | gitleaks blocks; customer content is license contamination. |

---

## 7. PR order

| PR | Track | Title | Depends on |
|----|-------|-------|------------|
| PR-1 | A-001 | Docs truth sweep (README stack table + stale OW-026 note + first log entry) | — |
| PR-2 | A-002 | Generated TS API client from OpenAPI (OW-015) | PR-1 |
| PR-3..n | A-003 | App.tsx decomposition series (hooks/stores, per-panel states, optimistic save) | PR-2 |
| PR-next | B-001 | Trace canvas badges → inspector wiring | A-003 (state extraction helps, not hard-depends) |
| PR-next | B-002 | Trace replay/step-through | B-001 |
| PR-rolling | C-001 | Playwright journeys (one journey = one small PR) | — (parallel anytime) |
| PR-last | B-003 | MPL comparison view | `api-request` fulfilled by backend |

---

## 8. Day-by-day (compressed first two weeks)

| Day | Work |
|-----|------|
| 1 | Bootstrap (Section 4). Read the last 3 log entries + this WP + `apps/web/README.md`. Run all checks green. PR-1 (docs truth sweep). |
| 2–3 | PR-2: generated API client; `api:gen` script; README update; e2e green untouched. |
| 4–7 | PR-3..n: decomposition series. One extraction per PR. File the B-003 `api-request` issue on day 4 so backend can schedule it. |
| 8–9 | B-001 canvas badges; B-002 step-through if ahead. |
| 10 | C-001: 2 new journeys (drag-drop persistence; validate-bad-flow). |
| 11+ | B-002 finish / B-003 if the endpoint landed / remaining C-001 journeys. |

---

## 9. Acceptance (work-package level)

### Foundations
- [ ] `api.ts` is generated (or a thin generated-types + hand wrapper hybrid), with `npm run api:gen` reproducible from the spec
- [ ] `App.tsx` < ~150 lines, layout-only; data/pending-ops logic in hooks/stores
- [ ] Per-panel loading + error states; no global error banner
- [ ] Optimistic pending-ops with single PATCH on save; no whole-flow reload on palette drop

### Trace v1.5
- [ ] Canvas badges reflect per-step trace verdicts; click selects the step in the inspector
- [ ] Replay/step-through renders every recorded exchange snapshot
- [ ] (if backend route landed) MPL comparison view reads cached calibration rows read-only

### E2E
- [ ] ≥ 7 of the 10 critical journeys covered, serial-safe, asserting UI == API truth
- [ ] Zero regressions to the EMG badge/chips truthfulness specs
- [ ] `tsc --noEmit`, `oxlint`, `vite build`, `playwright test` all green from a clean checkout

### Process
- [ ] Every PR appends a `DEVELOPMENT_LOG.md` entry; no history rewritten
- [ ] All branches cut from `origin/main`; nothing merged that touches `apps/cli/**` or server Python
- [ ] No `.oiw/` state, credentials, or tenant data committed or touched

---

## 10. Key files

| Area | Path |
|------|------|
| App shell (to decompose) | `apps/web/src/App.tsx`, `App.css`, `flow-utils.ts` |
| API layer (to generate) | `apps/web/src/api.ts`, `packages/api-spec/openapi.yaml` |
| Canvas | `apps/web/src/components/canvas/{FlowCanvas,PalettePanel,PropertiesPanel,TraceInspector}.tsx` |
| EMG (truthfulness contracts — careful) | `apps/web/src/components/emg/{EmgInsightPanel,InsightCard,PatternBrowser,TrajectoryViewer}.tsx` |
| Co-pilot | `apps/web/src/components/llm/{CoPilotPanel,PatchPreviewDialog,PlanApprovalDialog,TrajectoryIndicator}.tsx` |
| Deploy | `apps/web/src/components/deploy/{DeployPanel,ApprovalDialog,DeploymentStatusCard,DriftReportDialog}.tsx` |
| E2E | `apps/web/e2e/{copilot,emg-insights}.spec.ts`, `apps/web/playwright.config.ts` |
| CI (read-only for you) | `.github/workflows/{validate-on-pr,e2e}.yaml` |
| Log (append-only) | `DEVELOPMENT_LOG.md` |

---

## 11. Open questions

1. **Zustand or pure hooks for the state extraction (A-003)?** Backend has no opinion; announce the choice in the PR-2/PR-3 description since it's a new dependency either way.
2. **`reactflow` 11 vs README's "React Flow 12".** Resolve in A-001 (state the truth); upgrade only as a separate coordinated PR if ever.
3. **B-003 endpoint shape.** Proposal in the issue: `GET /api/v1/calibrations` returning cached report summaries. Backend may reshape it when implementing — consume whatever the spec says after his merge, not what this doc guessed.
4. **Where do generated client artifacts live?** Suggest `apps/web/src/api/gen/` + `src/api/client.ts` wrapper; commit generated output so CI doesn't need a generation step (matches existing CI shape).
