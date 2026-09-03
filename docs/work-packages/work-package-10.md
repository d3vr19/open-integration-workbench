# Work Package WP-10: Parallel Collaboration Sprint — Track D Unlock, Task Board, Contract-First API

**Status:** ACTIVE (2026-09-03, after B2 landed + campaign #1)
**Prerequisite:** WP-09 substantially complete (PR-1..PR-5 merged); B2 Experiment Engine live (`e6e7a95`)
**Participants:** backend/core engineer (B2, parity, tenant) + frontend engineer (expanded scope)
**Supersedes:** WP-09 §2.1 ownership matrix rows marked AMENDED below. WP-09 safety rules (§2.4) remain in full force, verbatim.

---

## 1. Why this package exists

The frontend engineer has capacity beyond `apps/web`. The serial `api-request` → backend-implements → frontend-consumes loop is the bottleneck. This package replaces it with **contract-first parallelism**: the OpenAPI spec is the review surface and the unblock mechanism; both sides run simultaneously; tasks carry written acceptance criteria so work is verifiable without synchronous coordination.

## 2. Amended ownership model

The WP-09 hard boundary (`apps/web` only) is AMENDED to **task-scoped shared ownership**:

- The frontend engineer may take bounded tasks ANYWHERE in the repo, provided:
  1. The task is on the WP-10 board (below) or added to it via a log entry, with acceptance criteria written BEFORE work starts.
  2. **File-family exclusivity**: a task never touches file families the backend engineer has declared "in-flight" that week (declared in DEVELOPMENT_LOG; current declaration in §5).
  3. Every shared-code PR is reviewed by the backend engineer — review is the safety net, not pre-approval conversation.
  4. WP-09 safety rules §2.4 apply unchanged: no tenant creds, no `.env`, no `oiw tenant/emg/agent/deploy` verbs, fixture workspaces in `/tmp` only, never commit `.oiw/` state (except the explicitly-committed artifacts listed in §6).
- The backend engineer keeps: tenant operations, the law-registry ratify gate, compiler/exporter semantics, experiment engine core, CI workflows.

## 3. Contract-first API protocol (replaces api-request round-trips)

1. Backend writes the OpenAPI additions FIRST (paths + schemas) — this is the contract review surface.
2. Frontend runs `npm run api:gen` immediately and builds against the generated types (mocked where routes haven't landed).
3. Backend lands routes; frontend switches mocks off. The e2e invariant extends: **UI == API truth** (assert against live API responses, never hardcoded counts).
4. Spec changes after a consumer lands require a deprecation note in the log — the generated client makes drift visible at `tsc` time.

**Landed with this package** (already in `packages/api-spec/openapi.yaml` + implemented):

| Endpoint | Serves | Status |
|----------|--------|--------|
| `GET /api/v1/experiments` | campaign summaries (verdict counts) | ✅ live |
| `GET /api/v1/experiments/{id}` | full rung records (verdicts, evidence) | ✅ live |
| `GET /api/v1/laws` | law registry (statements, predicates, status; filters: status, scope) | ✅ live |
| `GET /api/v1/projects/{id}/calibrations` | cached oracle report summaries | ✅ live |
| `GET /api/v1/projects/{id}/calibrations/{artifactId}` | full calibration report (MPL rows + reward) | ✅ live |

Fixture data for his e2e is COMMITTED (no tenant access needed): `docs/emg/experiments/exp-48bbffff92.yaml` (campaign #1), `packages/law-registry/tenant-laws.yaml` (2 ratified laws), `examples/*/. oiw/calibration-*.yaml`.

## 4. Task board (acceptance criteria = the review contract)

### Frontend track (H-tasks)

**H1 — Track D: Experiments & Laws panel** *(the big one; B2's gate opened with this package)*
- Acceptance: renders campaign records (rungs with GREEN/RED/SKIPPED badges, evidence incl. `targetType`, verdict tallies) + the law registry (status chips candidate/ratified/retired, source engine/manual, confidence, predicate when present); e2e asserts UI==API against `/experiments` + `/laws`; per-panel loading/error states (no global banner); works against BOTH a fixture workspace and the committed-registry fallback.
- Files: `apps/web/**` only. Suggested: `components/emg/` sibling `components/experiments/{ExperimentsPanel,LawRegistryPanel}.tsx`.

**H2 — B-003: tenant-MPL comparison view**
- Acceptance: side-by-side local trace (simulate) vs cached calibration MPL rows for the same artifact; epoch honesty (only rows ≥ `startedAt` shown as "this run"); e2e covers the comparison against the committed calibration fixture.
- Files: `apps/web/**`.

**H3 — Journeys #8–10 (OW-012 completion)**
- Acceptance: 10/10 critical journeys, serial-safe, UI==API assertions; candidates: (8) drag-drop persistence round-trip, (9) dirty-state + Save→PATCH, (10) laws/experiments panel journey (after H1).

**H4 — `splitter.general` real-engine implementation** *(good-first-issues #4; delegated to him)*
- Acceptance: true payload-splitting semantics in `apps/cli/oiw/runtime/steps/splitter.py` (fidelity `simulated` → real logic, mirroring `converter` implementations: unit tests with multi-element XML payloads, expression dialect `${property.x}` where the census shows it); `oiw test --engine real --project examples/sftp-order-drop` local verdict flips `UNSUPPORTED → PASS-or-honest-failure` (gather may still block: coordinate with H5).
- Files: `apps/cli/oiw/runtime/steps/splitter.py` + its test. **Backend stays out of that file until H4 merges.**

**H5 — `gather` real-engine implementation**
- Acceptance: same pattern as H4 in `gather.py`; together H4+H5 flip the `sftp-order-drop` parity case from `unsupported` to `comparable` (backend runs the oracle leg).

**H6 — Author 2–3 new parity-case example projects**
- Acceptance: each project passes `oiw validate --strict` + `oiw test --all` locally (simulated engine); uses ONLY proven pieces in proven placements (mirror `examples/oiw-conv-fwd` topology; consult `packages/law-registry/tenant-laws.yaml`); PR adds each to `packages/parity-corpus/manifest.yaml` as `pending-oracle`; backend runs the live calibrate leg and flips to comparable.
- Files: `examples/*`, `packages/parity-corpus/manifest.yaml`.

### Backend track (B-tasks, declared for the same window)

- **B-1**: fresh calibrate runs for H6 cases + campaign baselines → parity cases → gate ≥10 comparable (parity work is backend's; H4/H5/H6 feed it).
- **B-2**: `order-to-s4` XSLT2 problem (needs Saxon/JVM decision — architectural, NOT delegated).
- **B-3**: Mapping breadth (script-resource bundling → piece → campaign → law) — starts after the parity gate pushes.

## 5. File-family exclusivity (current declaration — update via log entries)

| File family | This sprint |
|-------------|-------------|
| `apps/web/**` | frontend (H1–H3) |
| `apps/cli/oiw/runtime/steps/splitter.py`, `gather.py` | frontend (H4/H5) — backend hands off |
| `examples/**`, `packages/parity-corpus/manifest.yaml` | frontend (H6) |
| `apps/cli/oiw/tenant/**`, `apps/cli/oiw/experiment/**`, `apps/cli/oiw/compiler/**` | backend |
| `packages/api-spec/openapi.yaml` | backend writes; frontend generates (api:gen) |
| `apps/server-python-prototype/**` | backend (new routes landed; additions via contract-first) |
| `.github/workflows/**` | backend |

## 6. Policy lines (non-negotiable)

1. **Law ratification stays CLI-only.** The human gate never becomes a UI button without an ADR. `/api/v1/laws` is read-only by design.
2. **Tenant credentials never travel to the frontend engineer.** Every task above is satisfiable against fixture + committed data.
3. **WP-09 §2.4 safety rules** carry over verbatim (env, tenant verbs, EMG store, honesty contracts).
4. **The log is the coordination plane**: every PR states its WP-10 task ID; file-family hand-offs are declared there.

## 7. Acceptance (sprint level)

- [ ] H1–H3 merged; laws/experiments visible in the workbench; 10/10 journeys green
- [ ] H4/H5 merged; `sftp-order-drop` parity case flips to comparable after backend's oracle run
- [ ] H6 cases in the manifest as pending-oracle; ≥2 flipped to comparable by B-1
- [ ] Parity gate: ≥10 comparable cases, agreement ≥90% held (currently 3/3 @ 100%)
- [ ] Zero cross-family merge conflicts; zero safety-rule violations

## 8. Committed artifacts this package introduces

- `apps/server-python-prototype/oiw_server/routes/experiments.py` + `calibrations.py` (+10 tests)
- `packages/api-spec/openapi.yaml`: Experiments/Laws/Calibrations tags, 5 paths, 6 schemas
- This document
