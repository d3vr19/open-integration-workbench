# Development Log — Open Integration Workbench

> **This file is the single source of truth for project state, decisions, deviations, and next steps.**
> Every agent (human or LLM) MUST read this file before working on the project and MUST append to it after producing a change.
> Format: append-only. Newest entries at the bottom. Never rewrite history; mark entries as superseded with a strikethrough note when needed.

| Field | Value |
|-------|-------|
| Project | Open Integration Workbench (OIW) |
| Spec version | 1.0.0 (2026-07-31) |
| Spec source | `spec/Untitled_6.md` (uploaded by user; canonical copy at upload time) |
| Repo | `https://github.com/hehenaice/open-integration-workbench` |
| License | Apache-2.0 |
| Current phase | Phase 3 — LLM-Assisted Engineering (substantially complete) |
| Phase exit criteria | See spec §19 |
| Last updated | 2026-08-01 |
| Total tests | 214 (77 CLI + 76 API + 18 MCP + 43 gateway) |
| CI checks | 10 required (validate-pr aggregate) |

---

## Table of Contents

1. [Phase Status](#phase-status)
2. [Architectural Decisions](#architectural-decisions)
3. [Implemented Components](#implemented-components)
4. [Deviation Registry](#deviation-registry)
5. [Open Work](#open-work)
6. [Change Log](#change-log)

---

## Phase Status

| Phase | Status | Target exit | Notes |
|-------|--------|-------------|-------|
| Phase 0 — Research & Compatibility Probe | COMPLETE (pending tenant test) | Spec §19 | IR schemas, archive inspector, minimal import/export, 2 golden fixtures + 3 negative fixtures; manual tenant acceptance test deferred (OW-010) |
| Phase 1 — Git-Native Headless Core | COMPLETE | Spec §19 | CLI, validator, semantic diff, compiler, Docker Compose, WSL2 bootstrap, 15 step plugins, 2 reference scenarios, typed patch engine |
| Phase 2 — Visual Workbench | SUBSTANTIALLY COMPLETE | Spec §19 | REST API (FastAPI), React 19 + React Flow 12 SPA, Monaco editor, drag-and-drop editing, simulation trace streaming, semantic diff viewer |
| Phase 3 — LLM-Assisted Engineering | SUBSTANTIALLY COMPLETE | Spec §19 | MCP server (11 tools), model gateway (redaction + budget + circuit breaker + prompt-injection defense), agent pipeline (requirement → plan → implement) |
| Phase 4 — Tenant Sync & CI/CD | NOT STARTED | Spec §19 | Deployment state machine, drift detection, tenant adapter |
| Phase 5 — Experience Memory Graph | NOT STARTED | Spec §19 | Trajectory recorder + graph matching + retrieval |
| Phase 6 — Compatibility Expansion | NOT STARTED | Spec §19 | Additional adapters (SOAP, OData, IDoc, Mail, JMS, SuccessFactors, ProcessDirect); SFTP receiver already implemented (simulated) |

---

## Architectural Decisions

Format: `ADR-<seq>: <decision>` — decisions superseding spec defaults are marked with `DEVIATION`.

### ADR-001: Canonical IR rather than archive-as-source
- **Spec ref:** §4.1, §4.2, §7
- **Status:** ADOPTED
- **Rationale:** Git-friendly text format decouples authoring from SAP proprietary artifact format. Enables semantic diff, deterministic builds, and LLM-friendly tooling.

### ADR-002: Original UI rather than SAP UI cloning
- **Spec ref:** §2.1, §2.2, §10.2
- **Status:** ADOPTED
- **Rationale:** Legal safety. Familiar integration terminology permitted; pixel-identical copy of SAP UI forbidden.

### ADR-003: Modular monolith first
- **Spec ref:** §4.8, §5.1
- **Status:** ADOPTED
- **Rationale:** Start as modular monolith with isolated workers; extract to microservices only when scale or security demands.

### ADR-004: JVM runtime worker for Groovy/XSLT
- **Spec ref:** §9, §16.1 threat 2
- **Status:** PLANNED (not yet implemented — runtime is currently Python prototype)
- **Rationale:** Process-isolated JVM with seccomp + network namespace for hostile Groovy scripts.

### ADR-005: Plugin SPI for steps and adapters
- **Spec ref:** §9.3
- **Status:** PARTIAL — Python plugin registry implemented (entry-point based); JVM SPI is future work.

### ADR-006: Git as source of truth
- **Spec ref:** §4.1, §11
- **Status:** ADOPTED — `.oiw/compiler.lock` records compiler version + digest per build; `dist/` is gitignored.

### ADR-007: Typed agent patches (never raw file edits)
- **Spec ref:** §12.1, §12.5
- **Status:** ADOPTED — `apps/cli/oiw/patch.py` implements 6 patch operations; used by both UI and MCP server.

### ADR-008: Approval-gated deployment
- **Spec ref:** §4.4, §15.2
- **Status:** SPEC ACCEPTED — implementation deferred to Phase 4.

### ADR-009: EMG with graph matching rather than unstructured pattern bank
- **Spec ref:** §13
- **Status:** SPEC ACCEPTED — implementation deferred to Phase 5.

### ADR-010: PostgreSQL/pgvector before dedicated graph DB
- **Spec ref:** §13.16
- **Status:** SPEC ACCEPTED — implementation deferred to Phase 5.

### ADR-011..020: per spec §25
- **Status:** SPEC ACCEPTED — individually addressed when their subsystems are implemented.

### ADR-PY-001: Phase 0/1 implementation language is Python (DEVIATION from spec §6.2)
- **Spec ref:** §6.2 (spec mandates Kotlin 2.1 + Spring Boot 3.4 + picocli CLI)
- **Status:** DEVIATION — TEMPORARY
- **Rationale:** Python for fast bootstrap; IR schemas, validation rules, test fixtures are language-agnostic and survive migration.
- **Migration plan:** OW-001.

### ADR-PY-002: Python FastAPI prototype for the REST API server (DEVIATION from spec §6.2)
- **Spec ref:** §6.2, §21.1
- **Status:** DEVIATION — TEMPORARY
- **Rationale:** Thin shim over `oiw` CLI; unblocks SPA development immediately. OpenAPI contract survives migration.
- **Migration plan:** OW-002.

### ADR-PY-003: Python MCP server prototype (DEVIATION from spec §5.1)
- **Spec ref:** §5.1, §12.4, §21.3
- **Status:** DEVIATION — TEMPORARY
- **Rationale:** Thin protocol adapter over `oiw` CLI; 11 MCP tools implemented and tested. JSON-RPC 2.0 over stdio.
- **Migration plan:** OW-002 (MCP server re-implemented in Kotlin alongside the server).

### ADR-PY-004: Python model gateway prototype (DEVIATION from spec §5.1)
- **Spec ref:** §5.1, §12.7
- **Status:** DEVIATION — TEMPORARY
- **Rationale:** FastAPI service with redaction, budget tracking, circuit breaker, prompt-injection defense. 5 LLM providers supported.
- **Migration plan:** OW-002 (model gateway re-implemented in Kotlin alongside the server).

### ADR-CI-001: GitHub Actions are the validation gate
- **Spec ref:** §14.4, §11.6
- **Status:** ADOPTED
- **Rationale:** 10 required CI jobs (validate-pr aggregate as required status check). Branch protection on `main`.

---

## Implemented Components

### Phase 0 / Phase 1

| Component | Location | Status | Notes |
|-----------|----------|--------|-------|
| Monorepo structure | `/` | DONE | Matches spec §20 |
| LICENSE, NOTICE, README, .gitignore | `/` | DONE | Apache-2.0; original branding; trademark notice |
| IR JSON Schemas | `packages/ir-schema/schemas/` | DONE | `oiw-project.json`, `integration-flow.json`, `flow-test.json`, `environment-profile.json` |
| `oiw` CLI | `apps/cli/oiw/` | DONE | `init`, `validate`, `test`, `build`, `diff`, `import`, `git status`, `archive inspect` |
| Project loader | `apps/cli/oiw/project.py` | DONE | Loads `oiw.yaml` + flow IR + tests + resources |
| Schema validator | `apps/cli/oiw/schema_validator.py` | DONE | jsonschema-based; runs on every write |
| Semantic graph validator | `apps/cli/oiw/validators/` | DONE | Connectedness, cycles, dangling refs, fidelity labels |
| Rule-based validator | `apps/cli/oiw/validators/rules.py` | DONE | `OIW-E001..E007`, `OIW-W001..W012` from spec §14.1 |
| Safe archive inspector | `apps/cli/oiw/archive.py` | DONE | Size limits, zip-bomb detection, path-traversal defense per spec §8.2 |
| Import parser (minimal) | `apps/cli/oiw/compiler/import_parser.py` | DONE | Parses the canonical minimal fixture into IR |
| Export compiler | `apps/cli/oiw/compiler/export.py` | DONE | Deterministic output; manifest + sha256 digest |
| Import report | `apps/cli/oiw/compiler/report.py` | DONE | `FULL \| PARTIAL \| FAILED` + recognized/opaque/unsupported per spec §8.3 |
| Semantic diff engine | `apps/cli/oiw/diff.py` | DONE | Structured diff (flows/resources/tests added/modified/removed) per spec §10.5 |
| Typed patch engine | `apps/cli/oiw/patch.py` | DONE | 6 operations: addNode, removeNode, updateNodeConfig, addEdge, removeEdge, moveNode per spec §12.5 |
| Local simulation runtime | `apps/cli/oiw/runtime/` | DONE | `MessageContext`, `ExecutionPlan`, step registry, trace_callback for streaming |
| Core step plugins (15) | `apps/cli/oiw/runtime/steps/` | DONE | sender.http, modifier.content, script.groovy (stub), transform.xslt, router.content-based, filter, converter.json-to-xml, converter.xml-to-json, encoder.base64, splitter.general, gather, receiver.http, receiver.sftp, validator.json-schema, log.message |
| Test runner | `apps/cli/oiw/testing.py` | DONE | Runs `FlowTest` IR; assertions: node.executed, outbound.request, exchange.status, etc. |
| Git status + commit proposal | `apps/cli/oiw/git_ops.py` | DONE | Reads HEAD revision; produces commit message proposal |
| Reference scenarios | `examples/order-to-s4/`, `examples/sftp-order-drop/` | DONE | 2 reference scenarios per spec §26.3 |
| Golden fixtures | `packages/test-fixtures/minimal/` | DONE | `https-content-modifier-http/` + `soap-groovy-sftp/` |
| Negative fixtures | `packages/test-fixtures/negative/` | DONE | `zip-bomb.zip`, `path-traversal.zip`, `corrupt-manifest.zip` |
| Docker Compose | `deploy/docker-compose/` | DONE | Matches spec §18.1; profiles for phase2-prototype, phase2, phase3, phase5, team |
| WSL2 bootstrap | `deploy/wsl/bootstrap.sh` | DONE | Phase 1 exit criterion per spec §18.3 |
| GitHub Actions | `.github/workflows/` | DONE | `validate-on-pr.yaml` (10 jobs), `security-scan.yaml`, `release.yaml` |
| ADRs | `docs/architecture/` | DONE | ADR-001..020 + ADR-PY-001..004 + ADR-CI-001 |
| Compatibility matrix | `docs/compatibility/matrix.md` | DONE | All 15 step plugins documented |
| Security threat model | `docs/security/threat-model.md` | DONE | Mirrors spec §16.1 |
| OpenAPI 3.1 spec | `packages/api-spec/openapi.yaml` | DONE | All REST endpoints documented |
| Rego policies | `packages/policy-rules/rego/` | DONE | Not yet wired into CLI (OW-008) |
| Semgrep rules | `packages/policy-rules/semgrep/` | DONE | Runs in CI |

### Phase 2 — Visual Workbench

| Component | Location | Status | Notes |
|-----------|----------|--------|-------|
| REST API server (FastAPI prototype) | `apps/server-python-prototype/` | DONE | ADR-PY-002. 76 tests. Swagger UI at /docs. |
| React SPA visual designer | `apps/web/` | DONE | React 19 + Vite 6 + React Flow 12 + Tailwind CSS 4 + Monaco Editor |
| Project explorer | `apps/web/src/App.tsx` | DONE | Left sidebar — projects, flows, palette, resources |
| Flow canvas | `apps/web/src/App.tsx` | DONE | React Flow 12 with dark theme, minimap, controls |
| Drag-and-drop node creation | `apps/web/src/App.tsx` | DONE | Palette → canvas drop → addNode patch |
| Editable properties panel | `apps/web/src/App.tsx` | DONE | Inline config editing, node ID editing |
| Save (PATCH flow) | `apps/web/src/App.tsx` | DONE | Accumulated ops → single PATCH → reload |
| Monaco resource editor | `apps/web/src/ResourceEditor.tsx` | DONE | Groovy/XSLT/JSON Schema inline editing |
| Resource explorer | `apps/web/src/App.tsx` | DONE | Left sidebar — lists all resources with language badges |
| Tabbed canvas | `apps/web/src/App.tsx` | DONE | Flow Canvas / Resource Editor tabs |
| Simulation trace panel | `apps/web/src/App.tsx` | DONE | Color-coded trace entries + outbound calls |
| Semantic diff viewer | `apps/web/src/DiffViewer.tsx` | DONE | Structured diff with color-coded entries |
| Validation panel | `apps/web/src/App.tsx` | DONE | Run `oiw validate --strict` from UI |
| Test runner panel | `apps/web/src/App.tsx` | DONE | Run `oiw test --all` from UI |
| Build panel | `apps/web/src/App.tsx` | DONE | Run `oiw build` from UI |
| Git status bar | `apps/web/src/App.tsx` | DONE | Branch, HEAD SHA, dirty flag, last build digest |
| WebSocket trace streaming | `apps/server-python-prototype/oiw_server/routes/simulate.py` | DONE | `/ws/trace` endpoint + POST `/simulate` |
| Resource read/write API | `apps/server-python-prototype/oiw_server/routes/resources.py` | DONE | GET/PUT resources with path traversal prevention |
| Diff API | `apps/server-python-prototype/oiw_server/routes/diff.py` | DONE | GET `/diff?rev=HEAD~1` structured diff |

### Phase 3 — LLM-Assisted Engineering

| Component | Location | Status | Notes |
|-----------|----------|--------|-------|
| MCP server (Python prototype) | `apps/mcp-server/` | DONE | ADR-PY-003. 11 tools, 18 tests. JSON-RPC 2.0 over stdio. |
| Model gateway (Python prototype) | `services/model-gateway-python/` | DONE | ADR-PY-004. 43 tests. Redaction, budget, circuit breaker, prompt-injection defense. |
| Agent pipeline | `apps/server-python-prototype/oiw_server/agent.py` | DONE | Requirements interpreter → integration planner → implementation agent. 17 tests. |
| POST /agents:plan endpoint | `apps/server-python-prototype/oiw_server/routes/agent.py` | DONE | Generate plan from NL requirement |
| POST /agents:implement endpoint | `apps/server-python-prototype/oiw_server/routes/agent.py` | DONE | Execute plan (dryRun supported) |
| Redaction layer | `services/model-gateway-python/oiw_gateway/redaction.py` | DONE | Strips secrets before LLM call (Bearer, API keys, passwords, PEM, tenant URLs) |
| Prompt-injection defense | `services/model-gateway-python/oiw_gateway/prompts.py` | DONE | 6 security rules per spec §16.3; cannot be overridden by user prompts |
| Budget tracker | `services/model-gateway-python/oiw_gateway/budget.py` | DONE | Per-project per-day token limit (default 2M); HTTP 429 when exhausted |
| Circuit breaker | `services/model-gateway-python/oiw_gateway/budget.py` | DONE | Per-provider; 5 failures → open; 60s reset → half-open → closed |
| Provider router | `services/model-gateway-python/oiw_gateway/providers.py` | DONE | Anthropic, OpenAI, Ollama, vLLM, Azure OpenAI |

### Deferred components

| Component | Phase | Notes |
|-----------|-------|-------|
| Kotlin/Spring Boot modular monolith | Phase 2+ | `apps/server/` — placeholder README; OW-002 |
| JVM runtime worker (process isolation, seccomp) | Phase 2+ | `services/runtime-worker/` — placeholder; Python prototype in `apps/cli/oiw/runtime/` for now; OW-003 |
| Tenant adapter | Phase 4 | Not yet implemented; OW-005 |
| EMG worker | Phase 5 | `services/emg-worker/` — placeholder README; OW-006 |
| Playwright E2E tests | Phase 2 exit | OW-012 |
| OPA/Rego wired into CLI | Phase 1 | OW-008 |

---

## Deviation Registry

| ID | Deviation | Spec ref | Severity | Migration target | Status |
|----|-----------|----------|----------|------------------|--------|
| DEV-001 | CLI implemented in Python, not Kotlin/picocli | §6.2 | Medium | OW-001 | Active, documented in ADR-PY-001 |
| DEV-002 | Server (Spring Boot modular monolith) not yet implemented; FastAPI prototype in use | §5.1, §6.2 | Medium | OW-002 | Tracked; ADR-PY-002 |
| DEV-003 | Runtime worker is Python in-process, not process-isolated JVM with seccomp | §9.6, §16.1 | High (security) | OW-003 | Tracked; do not run untrusted Groovy in current runtime |
| DEV-004 | ~~MCP server, model gateway not yet implemented~~ — DONE (Python prototypes, ADR-PY-003/004) | §12 | ~~High~~ Resolved | ~~OW-004~~ | Done |
| DEV-005 | Tenant adapter, deployment state machine not yet implemented | §15 | High (Phase 4 blocker) | OW-005 | Tracked |
| DEV-006 | EMG subsystem not yet implemented | §13 | Medium (Phase 5 blocker) | OW-006 | Tracked |
| DEV-007 | ~~Visual designer not yet implemented~~ — DONE (React 19 + React Flow 12 + Monaco) | §10 | ~~Medium~~ Resolved | ~~OW-007~~ | Done |
| DEV-008 | Rego (OPA) policies not yet wired into validator; Semgrep rules authored but not enforced in CLI | §14.2, §14.3 | Low | OW-008 | Tracked; GitHub Actions runs Semgrep |
| DEV-009 | ~~Agent pipeline is rule-based, not LLM-driven~~ — RESOLVED by WP-04 (LLM-driven interpreter + planner + executor with keyword fallback) | §12.2 | ~~Low~~ Resolved | None | Done; see WP-04 §10.1 |
| DEV-010 | Trajectory `normalized` tuple persisted as list for YAML compat | §15.4 | Low | None | Tracked; see WP-04 §10.3 |
| DEV-011 | Gateway client uses actual `/api/v1/llm/chat` endpoint, not aspirational `/v1/chat/completions` | §14 | Low | None | Tracked; see WP-04 §10.3 |
| DEV-012 | Redactor adds key-based redaction (stricter than spec §15.17) | §15.17 | Low | None | Tracked; see WP-04 §10.3 |
| DEV-013 | Fallback planner wraps legacy `plan_implementation()` in `_map_intent_to_legacy()` | §12.2 | Low | None | Tracked; see WP-04 §10.3 |
| DEV-014 | `tests/agent-eval/` → `tests/agent_eval/` (hyphen→underscore; Python module naming) | §27 | Low | None | Tracked; see WP-04 §10.6 |
| DEV-015 | 5 benchmarks defined but only 3 run in CI (bench-004/005 require LLM) | §27 | Low | None | Tracked; see WP-04 §10.6 |
| DEV-016 | Regression gate enforces bench-001 PASS (stricter than spec) | §27 | Low | None | Tracked; see WP-04 §10.6 |
| DEV-017 | `policy_violations` metric counts "ERROR" lines (coarse approximation) | §27 | Low | OW-024 | Tracked; see WP-04 §10.6 |
| DEV-018 | `test_pass_rate` metric parses "X/Y tests passed" text (fragile) | §27 | Low | OW-024 | Tracked; see WP-04 §10.6 |
| DEV-019 | No full SPA decomposition (only co-pilot components extracted) | §10 | Low | OW-029 | Tracked; see WP-04 §10.7 |
| DEV-020 | Trajectory ID not surfaced in UI (REST API doesn't return it) | §15.2 | Low | OW-027 | Tracked; see WP-04 §10.7 |
| DEV-021 | PatchPreviewDialog diff derived from stepResults, not `flow.semantic_diff` | §12.6 | Low | OW-028 | Tracked; see WP-04 §10.7 |
| DEV-022 | Playwright E2E not yet in CI (requires both Vite + Python server) | §10 | Medium | OW-026 | Tracked; see WP-04 §10.7 |
| DEV-023 | Bonus reject test (spec requires 1 E2E, implementation has 2) | §27 | Low | None | Tracked; see WP-04 §10.7 |
| DEV-024 | Eval harness at repo-root `tests/agent_eval/`, not `apps/cli/tests/agent_eval/` | §27 | Low | None | Tracked; see WP-04 §10.8. Rationale: eval harness is a cross-cutting benchmark suite, not a unit test; follows spec's literal `tests/agent-eval/` path. Migration path documented in WP-04 §10.8. |

---

## Open Work

| ID | Task | Phase | Priority | Depends on |
|----|------|-------|----------|------------|
| OW-001 | Migrate `apps/cli` from Python to Kotlin/picocli against existing JSON Schemas and test fixtures | Phase 1 exit | High | Phase 1 exit criteria verified |
| OW-002 | Implement `apps/server` Kotlin/Spring Boot modular monolith (REST + WebSocket + auth); replaces FastAPI prototype + MCP server + model gateway | Phase 2 | High | OW-001 |
| OW-003 | Implement `services/runtime-worker` Java 21 process-isolated JVM with seccomp + network namespace | Phase 2 | High (security) | OW-002 |
| OW-005 | Implement tenant adapter + deployment state machine + drift detection | Phase 4 | High | OW-002, OW-003 |
| OW-006 | Implement `services/emg-worker` (trajectory recorder, graph matching, retrieval) | Phase 5 | Medium | OW-002 |
| OW-008 | Wire OPA/Rego policy engine into CLI validator; enforce Semgrep rules locally | Phase 1 | Low | None |
| OW-010 | Manual tenant acceptance test against a real SAP CI dev tenant | Phase 0 exit | High (blocked) | Tenant access |
| OW-012 | Add UI E2E tests with Playwright (10 critical journeys) | Phase 2 exit | Medium | None |
| OW-013 | Add remaining §9.4 MVP step plugins: `sender.timer`, `subprocess.local`, `request-reply`, `datastore.write`, `datastore.read` | Phase 1 | Low | None |
| OW-014 | Add `odata-pagination-aggregation` golden fixture (requires `receiver.odata-v4` plugin — Phase 6) | Phase 6 | Low | OW-013 |
| OW-015 | Generate TypeScript API client from `packages/api-spec/openapi.yaml` (replace hand-written `apps/web/src/api.ts`) | Phase 2 | Low | None |
| OW-017 | Integrate model gateway with agent pipeline (LLM-assisted planning instead of rule-based) | Phase 3 | Medium | None |
| OW-018 | Add WebSocket real-time per-node trace streaming (currently buffered; true streaming needs JVM worker) | Phase 2 | Low | OW-003 |

---

## Change Log

Append new entries below. Newest at the bottom. Format:

```
### YYYY-MM-DD — <agent name / human> — <summary>
- Change 1
- Change 2
- Files touched: <paths>
- Tests: <pass/fail summary>
- CI: <workflow run link>
```

---

### 2026-07-31 — Implementing Agent (initial bootstrap) — Phase 0/1 skeleton + CLI MVP + CI

- Initialized monorepo structure per spec §20.
- Authored IR JSON Schemas per spec §7.
- Implemented `oiw` CLI in Python (ADR-PY-001).
- Implemented semantic graph validator, rule-based validator (OIW-E001..E007, OIW-W001..W012).
- Implemented safe archive inspector, deterministic export compiler, import report.
- Implemented local simulation runtime MVP with 9 step plugins.
- Built reference scenario `examples/order-to-s4/` + golden/negative fixtures.
- Authored GitHub Actions (validate-on-pr, security-scan, release).
- Created GitHub repo, pushed, CI green after jsonschema fix.
- Tests: 29/29 passed locally. CI: [run #30625738057](https://github.com/hehenaice/open-integration-workbench/actions/runs/30625738057).

### 2026-07-31 — Implementing Agent — Phase 1 completion: MVP step plugins + soap-groovy-sftp fixture + WSL2 bootstrap

- Implemented 6 new step plugins (splitter, gather, encoder.base64, filter, converter.xml-to-json, receiver.sftp). Total: 15 plugins.
- Added `soap-groovy-sftp` golden fixture (OW-009 partial).
- Added second reference scenario `examples/sftp-order-drop/`.
- Added WSL2 bootstrap (Phase 1 exit criterion, spec §18.3).
- Tests: 55/55 passed. CI: [run #30627024663](https://github.com/hehenaice/open-integration-workbench/actions/runs/30627024663). PR #1 merged.

### 2026-07-31 — Implementing Agent — Phase 2 REST API + React SPA starter

- Authored OpenAPI 3.1 spec (`packages/api-spec/openapi.yaml`).
- Implemented FastAPI prototype server (ADR-PY-002). 21 tests.
- Scaffolded React 19 + Vite 6 + React Flow 12 + Tailwind SPA.
- Three-pane layout: project explorer / flow canvas / properties + results.
- Added Docker Compose `phase2-prototype` profile.
- Tests: 76 total. CI: [run #30628666937](https://github.com/hehenaice/open-integration-workbench/actions/runs/30628666937). PR #2 merged.

### 2026-07-31 — Implementing Agent — Phase 2 interactive designer: typed patches + drag-and-drop + editable properties

- Implemented typed patch engine (`apps/cli/oiw/patch.py`) per spec §12.5. 6 operations.
- Added PATCH `/flows/{flowId}` endpoint. 22 CLI tests + 12 API tests.
- Added drag-and-drop node creation, editable properties panel, Save button, dirty-state tracking.
- Tests: 110 total. CI: [run #30630930615](https://github.com/hehenaice/open-integration-workbench/actions/runs/30630930615). PR #3 merged.

### 2026-07-31 — Implementing Agent — Phase 2 simulation trace streaming

- Extended runtime engine with `trace_callback` parameter for real-time streaming.
- Added POST `/simulate` endpoint + WebSocket `/ws/trace` endpoint.
- Added Simulate button + trace panel to SPA.
- Tests: 117 total. CI: [run #30643847848](https://github.com/hehenaice/open-integration-workbench/actions/runs/30643847848). PR #4 merged.

### 2026-07-31 — Implementing Agent — Phase 2 Monaco resource editor

- Added GET/PUT `/resources/{path}` endpoints with path traversal prevention. 13 tests.
- Added Monaco editor (`@monaco-editor/react`) with vs-dark theme.
- Added resource explorer in left sidebar + tabbed canvas area.
- Tests: 130 total. CI: [run #30647902601](https://github.com/hehenaice/open-integration-workbench/actions/runs/30647902601). PR #5 merged.

### 2026-07-31 — Implementing Agent — Phase 2 semantic diff viewer

- Added `structured_diff()` returning `StructuredDiff` dataclass.
- Added GET `/diff?rev=HEAD~1` endpoint. 6 tests.
- Added DiffViewer component with color-coded entries.
- Tests: 136 total. CI: [run #30649377082](https://github.com/hehenaice/open-integration-workbench/actions/runs/30649377082). PR #6 merged.

### 2026-07-31 — Implementing Agent — Phase 3 MCP server

- Implemented MCP server (ADR-PY-003). JSON-RPC 2.0 over stdio. 11 tools. 18 tests.
- Tools: project.list, flow.get, flow.patch, flow.validate, flow.simulate, resource.read, resource.write, test.run, test.create, build.export, git.status.
- Claude Desktop integration documented.
- Tests: 154 total. CI: [run #30650779595](https://github.com/hehenaice/open-integration-workbench/actions/runs/30650779595). PR #7 merged.

### 2026-07-31 — Implementing Agent — Phase 3 model gateway

- Implemented model gateway (ADR-PY-004). FastAPI service. 43 tests.
- Redaction layer (Bearer tokens, API keys, passwords, PEM keys, tenant URLs).
- Prompt-injection defense system prompt (§16.3).
- Per-project token budget tracker (default 2M/day, HTTP 429).
- Circuit breaker (5 failures → open, 60s reset, HTTP 503).
- 5 LLM providers: Anthropic, OpenAI, Ollama, vLLM, Azure.
- Tests: 197 total. CI: [run #30656351058](https://github.com/hehenaice/open-integration-workbench/actions/runs/30656351058). PR #8 merged.

### 2026-07-31 — Implementing Agent — Phase 3 agent pipeline

- Implemented agent pipeline (spec §12.2). 17 tests.
- Requirements Interpreter → Integration Planner → Implementation Agent.
- POST `/agents:plan` + POST `/agents:implement` endpoints.
- New MCP tool: `test.create`. Total MCP tools: 11.
- Tests: 214 total (77 CLI + 76 API + 18 MCP + 43 gateway). CI: [run #30660957965](https://github.com/hehenaice/open-integration-workbench/actions/runs/30660957965). PR #9 merged.

### 2026-08-01 — Implementing Agent — Documentation sync

- Comprehensive audit and update of DEVELOPMENT_LOG.md, README.md, and all docs to reflect the actual state after 9 merged PRs.
- Fixed phase statuses: Phase 2 and Phase 3 now marked "SUBSTANTIALLY COMPLETE".
- Updated implemented components table to include all Phase 2 and Phase 3 components.
- Updated deviation registry: DEV-004 and DEV-007 marked resolved; added DEV-009 (agent pipeline is rule-based, not LLM-driven).
- Updated open work: removed completed items (OW-004, OW-007, OW-009, OW-011, OW-016); added OW-017 (LLM-assisted planning) and OW-018 (true per-node WebSocket streaming).
- Updated README.md: status badge, features list, quick start, repo layout.
- Updated CI check count: 10 required jobs (was 6 at bootstrap).
- Total tests: 214 (was 29 at bootstrap).
- Files touched: DEVELOPMENT_LOG.md, README.md, docs/compatibility/matrix.md, docs/security/threat-model.md, docs/architecture/README.md, apps/web/README.md, apps/server/README.md, apps/mcp-server/README.md, services/model-gateway/README.md, services/runtime-worker/README.md, services/emg-worker/README.md

---


### 2026-08-02 — WP-04: LLM-Driven Agent Pipeline & Trajectory Instrumentation

- Implemented WP-04 Tasks 1–7 (8 deferred). New package `apps/cli/oiw/agent/`.
- **Task 1**: LLM-driven `interpret_requirement()` with keyword fallback. System
  prompt in `apps/cli/oiw/agent/prompts/interpreter.md`. Returns
  `NormalizedRequirement` with `intent`, `archetype`, `protocols`, `operations`,
  `components`, `constraints`, `confidence`. Emits `OIW-W014` on fallback.
- **Task 2**: LLM-driven `plan_implementation()` with hardcoded fallback.
  `TOOL_DEFINITIONS` passed as function-calling tools. Planner enforces
  `baseRevision` injection on every `flow.patch` step (defensive — even if the
  LLM omits it, the parser injects HEAD).
- **Task 3**: LLM-driven `execute_plan()` with bounded correction (max 2
  retries per failed step, spec §15.13). Pre-dispatch `baseRevision` validation
  returns `CONFLICT` status. Trajectory records every attempt.
- **Task 4**: `TrajectoryRecorder` persists to `.oiw/trajectories/{traj_id}.yaml`.
  Action normalization (spec §15.4): `(tool, op, componentType,
  semanticTarget, paramClass)`. Observation normalization (spec §15.5).
  Redaction (spec §15.17): regex patterns + key-based redaction (stricter than
  spec — catches `{"password": "pw"}` that regex misses).
- **Task 5**: `ModelGatewayClient` async HTTP client. Calls the gateway's
  actual `/api/v1/llm/chat` endpoint (not the aspirational
  `/v1/chat/completions` from WP-04 §3). `health()` returns False on network
  failure (never raises).
- **Task 6**: `baseRevision` now REQUIRED across all three layers:
  - MCP `flow.patch` schema lists `baseRevision` in `required` array;
    handler returns JSON-RPC `-32602` on missing/stale revision.
  - REST `PATCH /flows/{flowId}` returns HTTP 409 Conflict with structured
    body `{code: "BASE_REVISION_CONFLICT", clientRevision, serverRevision}`.
  - Agent executor validates `baseRevision` before dispatching; returns
    `CONFLICT` status on mismatch.
  - Existing `plan_implementation()` in
    `apps/server-python-prototype/oiw_server/agent.py` now accepts
    `base_revision` param and injects it into every `flow.patch` step.
  - Agent REST routes (`/agents:plan`, `/agents:implement`) now capture HEAD
    at planning time and pass it to the planner.
- **Task 7**: `run_agent()` orchestrator chains interpret → plan → (approve)
  → execute → trajectory. Two modes: `co-pilot` (default; approval callback)
  and `autonomous`. Computes reward vector
  `{structural_correctness, completion, corrections_needed, conflict_count}`.
- **Task 8 (Eval Harness)**: Deferred — requires spec §27 benchmark suite.
- **Task 9 (Co-Pilot UI)**: Deferred — React/Playwright work exceeds scope.
- **Corrections to WP-04 §2 "Current State" table** (see WP-04 §10.2):
  - `apps/cli/oiw/patch/` → actually `apps/cli/oiw/patch.py` (single file).
  - `apps/cli/oiw/agent/` → did not exist; legacy pipeline at
    `apps/server-python-prototype/oiw_server/agent.py`.
  - `apps/cli/oiw/agent/executor.py` → did not exist; was a function in the
    legacy agent.py.
  - baseRevision status → was accurate ("❌ Not passed by planner"); now fixed
    by Task 6.
- **Deviations** (see WP-04 §10.3):
  - DEV-010: Trajectory `normalized` tuple persisted as list for YAML compat.
  - DEV-011: Gateway client uses actual `/api/v1/llm/chat` endpoint, not
    aspirational `/v1/chat/completions`.
  - DEV-012: Redactor adds key-based redaction (stricter than spec §15.17).
  - DEV-013: Fallback planner wraps legacy `plan_implementation()` in
    `_map_intent_to_legacy()` to translate intent taxonomies.
- **Tests**: 294 total (153 CLI + 20 MCP + 78 server + 43 gateway).
  Baseline was 223. Delta: +71 (WP-04 required ≥35). CI: pending.
- **Open work items**:
  - OW-019: WP-04 Task 8 (Eval Harness) — author spec §27 benchmarks.
  - OW-020: WP-04 Task 9 (Co-Pilot UI) — React components + Playwright E2E.
  - OW-021: Wire `oiw agent` CLI command to `run_agent()` orchestrator.
  - OW-022: Add `oiw trajectory show` and `oiw trajectory export` CLI commands.


### 2026-08-02 (cont.) — WP-04 Task 8: Agent Evaluation Harness

- Implemented WP-04 Task 8 (Agent Evaluation Harness). 4 commits, 19 new tests.
- **Commit 1** (`6caf9e5`): benchmark definitions. `tests/agent_eval/benchmarks.py`
  defines 5 benchmarks (bench-001..005):
  - bench-001: Add schema validation (modify-flow, fast, CI)
  - bench-002: Create REST-to-HTTP flow (create-flow, CI)
  - bench-003: Fix receiver timeout (fix-flow, fast, CI)
  - bench-004: Add error handling subprocess (requires_llm)
  - bench-005: Refactor: extract common transform (requires_llm)
  - `ci_benchmarks()` returns bench-001..003 for the CI job.
- **Commit 2** (`5aa479f`): benchmark runner + metrics collection.
  `tests/agent_eval/metrics.py` defines `BenchmarkMetrics` (9 fields per
  spec §27: structural_correctness, test_pass_rate, policy_violations,
  human_corrections, token_cost, latency_ms, hallucinated_components,
  secret_handling_violations, trajectory_id) and `BenchmarkResult` with
  PASS/PARTIAL/FAIL classifier (thresholds: >=0.9 PASS, >=0.5 PARTIAL).
  `tests/agent_eval/runner.py` implements `run_benchmark_fallback()`
  (executes one benchmark via the orchestrator with gateway mocked
  unhealthy) and `run_ci_suite()` (runs bench-001..003 and emits a YAML
  report). CLI entry: `python -m tests.agent_eval.runner`.
- **Commit 3** (`8cb09af`): eval harness tests. 19 tests total, including
  the 2 mandatory WP-04 tests:
  - `test_benchmark_001_without_llm`: fallback planner passes bench-001
  - `test_benchmark_001_with_mock`: mock gateway returns valid plan,
    bench-001 still passes
  Bonus coverage: classifier thresholds (8 tests), benchmark catalogue
  (6 tests), CI suite runner (2 tests), serialization (1 test).
- **Commit 4** (`a1385fc`): CI workflow. `.github/workflows/agent-eval.yaml`
  with two jobs:
  - `agent-eval-fallback`: runs pytest on the harness, then runs the CI
    suite (bench-001..003), then enforces a regression gate (bench-001
    MUST PASS; bench-002/003 may FAIL/PARTIAL; no benchmark may EROR).
    Uploads the YAML report + .oiw/agent-eval/ workspaces as artifacts
    (30-day retention). Runs on every PR/push + nightly at 03:00 UTC.
  - `agent-eval-aggregate`: required status check for branch protection.
  Updated `.github/workflows/validate-on-pr.yaml` aggregate job to note
  that branch protection should require BOTH `validate-pr (aggregate)`
  AND `agent-eval (aggregate)`.
- **Baseline metrics** captured at
  `tests/agent_eval/baselines/baseline-fallback-2026-08-02.yaml`:
  - bench-001: PASS (structural=1.00, tests=1.00, latency=1419ms, tokens=0)
  - bench-002: FAIL (structural=0.20, tests=0.00, latency=22ms, tokens=0)
  - bench-003: PARTIAL (structural=0.75, tests=1.00, latency=26ms, tokens=0)
  These are the expected fallback limitations — the LLM planner should
  close the bench-002 and bench-003 gaps when wired in.
- **Deviations** (see WP-04 §10.6):
  - DEV-014: `tests/agent-eval/` → `tests/agent_eval/` (Python module
    naming; hyphen not allowed).
  - DEV-015: 5 benchmarks defined but only 3 run in CI (bench-004/005
    require LLM; matches spec's "CI runs 001-003, nightly runs full").
  - DEV-016: Regression gate enforces bench-001 PASS (stricter than
    spec, which doesn't specify a gate).
  - DEV-017: `policy_violations` metric counts "ERROR" lines in
    `oiw validate --strict` output (coarse; future: parse structured
    diagnostics).
  - DEV-018: `test_pass_rate` metric parses "X/Y tests passed" from
    `oiw test --all` output (fragile; future: use TestResult objects).
- **Test count**: 294 → 313 (+19). CI: 10 existing jobs + 1 new
  `agent-eval` job = 11 total.
- **Process note acknowledged**: Future work packages will use smaller
  commits (one per task or logical unit). Task 8 was committed in 4
  smaller commits (benchmarks, runner+metrics, tests, CI) plus a 5th
  for docs/baseline — much more bisect-friendly than the 30-file Task
  1-7 commit.
- **Open work items**:
  - OW-023: Wire the LLM planner into bench-002 and bench-003 to close
    the fallback gaps (bench-002 FAIL→PASS, bench-003 PARTIAL→PASS).
  - OW-024: Replace the coarse `policy_violations` and `test_pass_rate`
    metric parsers with structured-diagnostic readers.
  - OW-025: Add bench-004 and bench-005 to the nightly LLM suite
    (requires OIW_MODEL_GATEWAY_KEY in CI secrets).


### 2026-08-02 (cont. 2) — WP-04 Task 9: Co-Pilot UI Panel

- Implemented WP-04 Task 9 (Co-Pilot UI Panel). 5 commits, 2 E2E tests.
- **Commit 1** (`2db0390`): extend api.ts with agent endpoints.
  Added `api.plan()` and `api.implement()` methods + types
  (NormalizedRequirement, PlanStep, AgentPlanResponse, StepResult,
  AgentImplementResponse). Matches the REST routes in
  `apps/server-python-prototype/oiw_server/routes/agent.py`.
- **Commit 2** (`33f0640`): three supporting components.
  - TrajectoryIndicator.tsx: pulsing red dot while recording, green when
    recorded, red on failure.
  - PlanApprovalDialog.tsx: modal showing requirement summary, numbered
    steps with tool labels + argument summaries, assumptions, risks,
    Approve/Reject buttons.
  - PatchPreviewDialog.tsx: modal showing applied changes, color-coded
    (added=green, removed=red, changed=yellow, resource=blue),
    success/failure counts, step results.
- **Commit 3** (`6cb4c68`): CoPilotPanel.tsx + ~400 lines of CSS.
  The main chat interface. State machine: idle → planning → plan-ready →
  executing → applied (or error). Calls api.plan() on Suggest,
  api.implement() on Approve. Suggestions list, history (last 3),
  Ctrl+Enter shortcut. Trajectory indicator pulses during recording.
- **Commit 4** (`7252ecb`): wire CoPilotPanel into App.tsx.
  Added refreshFlow() callback. Inserted CoPilotPanel as the first
  section in the right sidebar (above Node Properties). The panel
  receives projectId, flowId, onApplied=refreshFlow.
- **Commit 5** (`f6fa1fa`): Playwright E2E test.
  - apps/web/playwright.config.ts: chromium, single worker, serial mode,
    auto-starts Vite dev server.
  - apps/web/e2e/copilot.spec.ts: 2 tests:
    * test_copilot_suggest_and_apply (MANDATORY): opens app → selects
      project+flow → types requirement → clicks Suggest → verifies
      PlanApprovalDialog → clicks Approve & Execute → verifies
      PatchPreviewDialog → closes → verifies validator node on canvas.
    * test_copilot_reject_plan (bonus): verifies reject path closes
      dialog without adding nodes.
  - Both tests verified passing locally (3.0s + 1.0s = 4.0s total).
- **Deviations** (see WP-04 §10.7):
  - DEV-019: No full SPA decomposition (only co-pilot components
    extracted; FlowCanvas/PropertiesPanel/PalettePanel remain in
    App.tsx per spec note "full decomposition is a separate work
    package").
  - DEV-020: Trajectory ID not surfaced in UI (REST API doesn't
    return it; TrajectoryIndicator shows 'recorded' without ID).
  - DEV-021: PatchPreviewDialog diff is derived from stepResults, not
    fetched from flow.semantic_diff (simplification; future iteration
    should fetch real structural diff).
  - DEV-022: Playwright E2E not yet in CI (requires both Vite + Python
    server; tracked as OW-026).
  - DEV-023: Bonus reject test (spec requires 1, implementation has 2).
- **Test count**: 313 unit/integration + 2 E2E = 315 total.
- **WP-04 acceptance**: 15/15 criteria now met (all checkboxes [x]).
- **Open work items**:
  - OW-026: Add `e2e` CI job (install Playwright browsers, start Python
    server + Vite, run tests, upload report).
  - OW-027: Return trajectoryId from POST /agents:implement so UI can
    link to `oiw trajectory show --id <id>`.
  - OW-028: Fetch real semantic diff in PatchPreviewDialog (call
    flow.semantic_diff instead of deriving from stepResults).
  - OW-029: Full SPA decomposition (extract FlowCanvas, PropertiesPanel,
    PalettePanel from App.tsx — separate work package).


### 2026-08-02 (cont. 3) — CI green + OW-026/027/028 complete

- **CI fully green** on commit `ffa1963` — all 4 workflows pass:
  - Security Scan: success
  - Validate PR: success (all 9 jobs: OIW validate, schema self-check,
    CLI pytest, API pytest, MCP pytest, gateway pytest, ruff lint, SPA
    build, DEVELOPMENT_LOG check)
  - Agent Eval: success (bench-001 PASS, bench-002 FAIL, bench-003 PARTIAL)
  - E2E Tests: success (2 Playwright tests pass)
- **CI fix history** (8 passes to resolve all issues):
  1. httpx missing from CLI dependencies
  2. pytest-asyncio missing from CLI [dev] extras
  3. ruff 0.5.7 format compatibility (UP038, SIM102, SIM108, BLE001, etc.)
  4. Agent-eval runner exit code (bench-002 FAIL is expected, not an error)
  5. E402 noqa for sys.path-gated imports in eval harness
  6. ruff-formatted files not staged (agent source, agent tests, server-prototype)
  7. PYTHONPATH missing from CI CLI pytest job (executor tests need MCP server)
  8. --forbid-flaky not supported in installed Playwright version
- **OW-026 complete**: E2E CI workflow (`.github/workflows/e2e.yaml`) runs
  Playwright tests on every PR/push. Sets up Python API server + Vite dev
  server + chromium. Both co-pilot tests pass in CI.
- **OW-027 complete**: POST /agents:implement now returns `trajectoryId`.
  The route wraps the legacy executor in a TrajectoryRecorder, persists
  the trajectory YAML, and returns the ID. CoPilotPanel surfaces it in
  the TrajectoryIndicator tooltip. +2 server tests.
- **OW-028 complete**: PatchPreviewDialog now fetches the real semantic
  diff from GET /projects/{id}/diff instead of deriving from stepResults.
  Falls back to derived diff on error. Shows trajectory ID badge.
- **Test count**: 313 → 317 (315 unit/integration + 2 E2E). All green in CI.
- **CI checks**: 12 required checks across 3 workflows (validate-on-pr,
  agent-eval, e2e).
- **DEV-020 resolved** (trajectory ID surfaced) by OW-027.
- **DEV-021 resolved** (real semantic diff) by OW-028.
- **DEV-022 resolved** (Playwright E2E in CI) by OW-026.
- **Remaining open work**: OW-029 (full SPA decomposition — separate WP).


### 2026-08-03 — WP-05: Tenant Deployment Pipeline + EMG Phase B

- Implemented WP-05 Tasks 1-15 (Tasks 16-17 deferred). 7 commits.
- **Track A (Tenant Deployment Pipeline):**
  - Task 1: EnvironmentProfile loader + validator (8 tests)
  - Task 2: TenantAdapter Protocol + MockSapCiTenantAdapter + stub (12 tests)
  - Task 3: DeploymentStateMachine (8 tests)
  - Task 4: DriftDetector (5 tests)
  - Task 5: CI/CD templates (oiw-validate.yaml, oiw-deploy.yaml) + docs
  - Task 6: 'oiw deploy' CLI command (7 subcommands: check-drift, propose,
    approve, upload, execute, verify, status) (5 tests)
  - Task 7: post-deployment smoke test (verify command → VERIFIED)
- **Track B (EMG Phase B — Intra-Task Correction):**
  - Task 8: ActionDecisionGraphBuilder (5 tests)
  - Task 9: ExactMatcher (4 tests)
  - Task 10: RuleBasedMatcher (4 tests)
  - Task 11: CommonSubgraphExtractor (3 tests)
  - Task 12: GraphEditPathExtractor (4 tests)
  - Task 13: IntraTaskInsightCompiler (3 tests)
  - Task 14: MemoryPromotionWorkflow (8 tests)
  - Task 15: RewardVector extension to 9 dimensions (6 tests)
- **Test count**: 317 → 371 (+54). All passing.
  - CLI: 153 → 228 (+75, includes 38 WP-04 agent + 37 WP-05)
  - MCP: 20 (unchanged)
  - Server: 80 (unchanged)
  - Gateway: 43 (unchanged)
  - Agent Eval: 19 (unchanged)
  - E2E: 2 (unchanged)
- **CI fixes during WP-05:**
  - Added networkx to CLI dependencies (Task 8 imports it)
  - Replaced asyncio.get_event_loop() with asyncio.run() (Python 3.12 compat)
  - Added approvalTtlHours to EnvironmentProfile JSON Schema
- **New packages:**
  - apps/cli/oiw/environments.py — profile loading
  - apps/cli/oiw/tenant/ — adapter interface + mock + stub
  - apps/cli/oiw/deploy/ — state machine + drift detector
  - apps/cli/oiw/emg/ — graph builder, matching, subgraph, insight, promotion, reward
  - packages/ci-templates/ — reusable GitHub Actions workflows
  - docs/ci-cd/github-actions.md — setup guide
- **Deferred:**
  - Task 16 (Full SPA decomposition, OW-029) — separate work package
  - Task 17 (Eval harness LLM integration, OW-023/024) — requires live LLM
- **WP-05 acceptance criteria**: 12/17 met (Tasks 16-17 deferred).
  Core pipeline + EMG Phase B fully functional.


### 2026-08-03 (cont.) — WP-05 Task 17: OW-023 + OW-024 complete

- **OW-024**: Added `--json` flag to `oiw validate` and `oiw test` commands.
  Structured JSON output: `{passed, errors[], error_count}` for validate,
  `{passed, pass_rate, total, results[]}` for test. Eval harness now
  parses JSON instead of regex on text output. Closes DEV-017 + DEV-018.
- **OW-023**: LLM-backed benchmark runner (`tests/agent_eval/llm_runner.py`)
  using the z-ai CLI (`z-ai chat`). Sends a structured prompt with
  requirement + project context + HEAD sha, parses the JSON plan response,
  and executes via the orchestrator. Verified locally:
  - bench-003 (Fix receiver timeout): PARTIAL, structural=0.75, latency=6s
  - bench-002 (Create REST-to-HTTP flow): FAIL, structural=0.20, latency=19s
  bench-002 still fails because the new-project scaffold doesn't have a
  flow to patch — needs a 'create flow' MCP tool (future work).
- **Test count**: 371 → 382 (+11 from OW-023/024 tests).
  - Agent Eval: 19 → 30 (+11: 5 prompt building + plan parsing, 1 z-ai
    CLI integration, 2 structured metric parity, 3 LLM runner plumbing)
- **z-ai SDK**: Used the `z-ai chat` CLI from Python via subprocess.
  The ZAI SDK is available in this environment (confirmed working).
  LLM benchmarks are NOT in CI (require network access); they run
  manually via `python -m tests.agent_eval.llm_runner -b bench-003`.
- **WP-05 status**: Tasks 1-15 + Task 17 complete. Only Task 16 (full
  SPA decomposition, OW-029) remains deferred.

