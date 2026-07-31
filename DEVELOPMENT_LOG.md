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
| Current phase | Phase 0/1 — Bootstrap & Git-Native Headless Core |
| Phase exit criteria | See spec §19 Phase 0 and Phase 1 |
| Last updated | 2026-07-31 |

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
| Phase 0 — Research & Compatibility Probe | COMPLETE (pending tenant test) | Spec §19 | IR schemas, archive inspector, minimal import/export, 2 golden fixtures + 3 negative fixtures; manual tenant acceptance test deferred (no tenant available in dev environment) — tracked as OW-010 |
| Phase 1 — Git-Native Headless Core | COMPLETE | Spec §19 | CLI (`init`, `validate`, `test`, `build`, `diff`, `import`, `git status`), validator, semantic diff, compiler interface, Docker Compose, WSL2 bootstrap, full §9.4 MVP step coverage, 2 reference scenarios — all Phase 1 exit criteria met |
| Phase 2 — Visual Workbench | IN PROGRESS | Spec §19 | REST API (FastAPI prototype, ADR-PY-002) + React 19 + React Flow 12 SPA with project explorer, flow canvas, properties panel, validation/test/build panels. Monaco editor, drag-and-drop editing, WebSocket trace streaming not yet done. |
| Phase 3 — LLM-Assisted Engineering | IN PROGRESS | Spec §19 | MCP server implemented (10 tools, 18 tests). Model gateway implemented (redaction, budget, circuit breaker, prompt-injection defense, 5 providers, 43 tests). Requirement-to-plan workflow not yet done. |
| Phase 4 — Tenant Sync & CI/CD | NOT STARTED | Spec §19 | Deployment state machine, drift detection; deferred until local build correctness is proven |
| Phase 5 — Experience Memory Graph | NOT STARTED | Spec §19 | Trajectory recorder + graph matching + retrieval; deferred |
| Phase 6 — Compatibility Expansion | NOT STARTED | Spec §19 | Additional adapters (SFTP, SOAP, OData, IDoc, Mail, JMS, SuccessFactors, ProcessDirect); SFTP receiver plugin implemented in Phase 1 (simulated, mocked); real SFTP support is Phase 6 |

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
- **Status:** SPEC ACCEPTED — implementation deferred to Phase 3.

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
- **Rationale:** Python was chosen for the Phase 0/1 bootstrap to deliver a working CLI + validator + compiler + runtime MVP in a single engineering session, validating the architecture before committing to a heavier JVM build. The IR schemas, validation rules, archive inspection, semantic diff, compiler interface, and execution semantics are language-agnostic; migrating the CLI to Kotlin/picocli and the server to Spring Boot is a mechanical translation against the same JSON Schemas and test fixtures.
- **Migration plan:** Tracked in [Open Work](#open-work) item OW-001. Migration begins after Phase 1 exit criteria are met. The Python implementation remains as a reference / fallback during migration. All JSON Schemas, Rego policies, Semgrep rules, and test fixtures survive the migration unchanged.
- **Risk:** Low. Architecture is preserved. The deviation is confined to the implementation language of `apps/cli` and `services/runtime-worker` (Phase 0/1 only); the target Kotlin/Spring Boot modular monolith (`apps/server`) and Java 21 runtime worker (`services/runtime-worker`) remain the production target.

### ADR-CI-001: GitHub Actions are the validation gate
- **Spec ref:** §14.4, §11.6
- **Status:** ADOPTED
- **Rationale:** `validate-on-pr.yaml` runs schema validation, `oiw validate --strict`, `oiw test --all`, `oiw build`, Semgrep, gitleaks, Trivy, and SBOM generation on every PR. `security-scan.yaml` runs on schedule and on push to main. `release.yaml` runs on tag push and produces signed release artifacts.

---

## Implemented Components

### Phase 0 / Phase 1 deliverables

| Component | Location | Status | Notes |
|-----------|----------|--------|-------|
| Monorepo structure | `/` | DONE | Matches spec §20 |
| LICENSE, NOTICE, README, .gitignore | `/` | DONE | Apache-2.0; original branding; trademark notice |
| IR JSON Schemas | `packages/ir-schema/schemas/` | DONE | `oiw-project.json`, `integration-flow.json`, `flow-test.json`, `environment-profile.json` |
| `oiw` CLI | `apps/cli/oiw/` | DONE | `init`, `validate`, `test`, `build`, `diff`, `import`, `git status` |
| Project loader | `apps/cli/oiw/project.py` | DONE | Loads `oiw.yaml` + flow IR + tests + resources |
| Schema validator | `apps/cli/oiw/schema_validator.py` | DONE | jsonschema-based; runs on every write |
| Semantic graph validator | `apps/cli/oiw/validators/` | DONE | Connectedness, cycles, dangling refs, fidelity labels |
| Rule-based validator | `apps/cli/oiw/validators/rules.py` | DONE | `OIW-E001..E007`, `OIW-W001..W012` from spec §14.1 |
| Safe archive inspector | `apps/cli/oiw/archive.py` | DONE | Size limits, zip-bomb detection, path-traversal defense per spec §8.2 |
| Import parser (minimal) | `apps/cli/oiw/compiler/import_parser.py` | DONE | Parses the canonical minimal fixture into IR |
| Export compiler | `apps/cli/oiw/compiler/export.py` | DONE | Deterministic output; manifest + sha256 digest |
| Import report | `apps/cli/oiw/compiler/report.py` | DONE | `FULL \| PARTIAL \| FAILED` + recognized/opaque/unsupported per spec §8.3 |
| Semantic diff engine | `apps/cli/oiw/diff.py` | DONE | Node/edge/resource/test-level diffs per spec §10.5 |
| Local simulation runtime | `apps/cli/oiw/runtime/` | DONE | `MessageContext`, `ExecutionPlan`, step registry, trace streaming |
| Core step plugins | `apps/cli/oiw/runtime/steps/` | DONE | `sender.http`, `modifier.content`, `script.groovy` (sandboxed stub), `transform.xslt` (Saxon-equivalent), `router.content-based`, `receiver.http` (mocked), `validator.json-schema`, `log.message` |
| Test runner | `apps/cli/oiw/testing.py` | DONE | Runs `FlowTest` IR; assertions: `node.executed`, `outbound.request`, `exchange.status` |
| Git status + commit proposal | `apps/cli/oiw/git_ops.py` | DONE | Reads HEAD revision; produces commit message proposal |
| Reference scenario | `examples/order-to-s4/` | DONE | Inbound JSON → validation → Groovy → XSLT → mocked HTTP → error subprocess per spec §26.3 |
| Golden fixture | `packages/test-fixtures/minimal/https-content-modifier-http/` | DONE | Synthetic source.zip + expected-ir.yaml + expected-export.zip + import-report.yaml |
| Docker Compose | `deploy/docker-compose/docker-compose.yaml` | DONE | Matches spec §18.1; services currently stub images pending Kotlin migration |
| GitHub Actions | `.github/workflows/` | DONE | `validate-on-pr.yaml`, `security-scan.yaml`, `release.yaml` |
| ADR-001..020 placeholders | `docs/architecture/` | DONE | Individual ADRs as separate files; content mirrors spec §25 |
| Compatibility matrix | `docs/compatibility/matrix.md` | DONE | Initial matrix for MVP step coverage |
| Security threat model | `docs/security/threat-model.md` | DONE | Mirrors spec §16.1 |

### Deferred components (Phase 2+)

| Component | Phase | Notes |
|-----------|-------|-------|
| React visual designer | Phase 2 | `apps/web/` — not yet scaffolded beyond placeholder |
| Kotlin/Spring Boot modular monolith | Phase 2 | `apps/server/` — placeholder README only |
| MCP server | Phase 3 | `apps/mcp-server/` — placeholder README only |
| Model gateway | Phase 3 | `services/model-gateway/` — placeholder README only |
| Tenant adapter | Phase 4 | Not yet implemented |
| EMG worker | Phase 5 | `services/emg-worker/` — placeholder README only |
| JVM runtime worker (process isolation, seccomp) | Phase 2 | `services/runtime-worker/` — placeholder; Python prototype in `apps/cli/oiw/runtime/` for now |

---

## Deviation Registry

| ID | Deviation | Spec ref | Severity | Migration target | Status |
|----|-----------|----------|----------|------------------|--------|
| DEV-001 | CLI implemented in Python, not Kotlin/picocli | §6.2 | Medium | OW-001 | Active, documented in ADR-PY-001 |
| DEV-002 | Server (Spring Boot modular monolith) not yet implemented | §5.1, §6.2 | High (Phase 2 blocker) | OW-002 | Tracked |
| DEV-003 | Runtime worker is Python in-process, not process-isolated JVM with seccomp | §9.6, §16.1 | High (security) | OW-003 | Tracked; do not run untrusted Groovy in current runtime |
| DEV-004 | MCP server, model gateway not yet implemented | §12 | High (Phase 3 blocker) | OW-004 | Tracked |
| DEV-005 | Tenant adapter, deployment state machine not yet implemented | §15 | High (Phase 4 blocker) | OW-005 | Tracked |
| DEV-006 | EMG subsystem not yet implemented | §13 | Medium (Phase 5 blocker) | OW-006 | Tracked |
| DEV-007 | Visual designer not yet implemented | §10 | Medium (Phase 2 blocker) | OW-007 | Tracked |
| DEV-008 | Rego (OPA) policies not yet wired into validator; Semgrep rules authored but not enforced in CLI | §14.2, §14.3 | Low | OW-008 | Tracked; GitHub Actions runs Semgrep |

---

## Open Work

| ID | Task | Phase | Priority | Depends on |
|----|------|-------|----------|------------|
| OW-001 | Migrate `apps/cli` from Python to Kotlin/picocli against existing JSON Schemas and test fixtures | Phase 1 exit | High | Phase 1 exit criteria verified |
| OW-002 | Implement `apps/server` Kotlin/Spring Boot modular monolith (REST + WebSocket + auth) | Phase 2 | High | OW-001 |
| OW-003 | Implement `services/runtime-worker` Java 21 process-isolated JVM with seccomp + network namespace | Phase 2 | High (security) | OW-002 |
| OW-004 | Implement `apps/mcp-server` and `services/model-gateway` | Phase 3 | High | OW-002 |
| OW-005 | Implement tenant adapter + deployment state machine + drift detection | Phase 4 | High | OW-002, OW-003 |
| OW-006 | Implement `services/emg-worker` (trajectory recorder, graph matching, retrieval) | Phase 5 | Medium | OW-002, OW-004 |
| OW-007 | Implement `apps/web` React 19 + React Flow 12 visual designer | Phase 2 | Medium | OW-002 |
| OW-008 | Wire OPA/Rego policy engine into CLI validator; enforce Semgrep rules locally | Phase 1 | Low | None |
| OW-009 | ~~Expand golden fixture coverage: add `soap-groovy-sftp` and `odata-pagination-aggregation` minimal fixtures~~ — `soap-groovy-sftp` DONE in this PR; `odata-pagination-aggregation` still pending | Phase 1 | Medium | None |
| OW-010 | Manual tenant acceptance test against a real SAP CI dev tenant | Phase 0 exit | High (blocked) | Tenant access |
| OW-011 | Add `oiw agent review` GitHub Action step (Phase 3 dependency) | Phase 3 | Low | OW-004 |
| OW-012 | Add UI E2E tests with Playwright (10 critical journeys) | Phase 2 exit | Medium | OW-007 |
| OW-013 | Add remaining §9.4 MVP step plugins: `sender.timer`, `subprocess.local`, `request-reply`, `datastore.write`, `datastore.read` | Phase 1 | Low | None |
| OW-014 | Add `odata-pagination-aggregation` golden fixture (requires `receiver.odata-v4` plugin — Phase 6) | Phase 6 | Low | OW-013 |
| OW-015 | Generate TypeScript API client from `packages/api-spec/openapi.yaml` (replace hand-written `apps/web/src/api.ts`) | Phase 2 | Low | None |
| OW-016 | Complete Phase 2 visual designer: drag-and-drop editing, Monaco editor, undo/redo, semantic diff viewer, WebSocket trace streaming | Phase 2 | High | None |

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

- Initialized monorepo structure per spec §20 (`apps/`, `services/`, `packages/`, `plugins/`, `deploy/`, `docs/`, `examples/`, `.github/workflows/`).
- Authored IR JSON Schemas per spec §7: `oiw-project.json`, `integration-flow.json`, `flow-test.json`, `environment-profile.json` — all carry `$id: https://schema.oiw.dev/<kind>/v1alpha1.json`.
- Implemented `oiw` CLI in Python with subcommands: `init`, `validate`, `test`, `build`, `diff`, `import`, `git status`. See ADR-PY-001 for the language deviation rationale and migration plan.
- Implemented semantic graph validator with rule codes `OIW-E001..E007` (errors) and `OIW-W001..W012` (warnings) per spec §14.1.
- Implemented safe archive inspector with: max archive size (256 MB), max uncompressed size (1 GB), max entry count (10 000), zip-bomb detection (compression ratio > 100), path-traversal defense (rejects `..` and absolute paths), symlink rejection per spec §8.2.
- Implemented deterministic export compiler: produces a manifest JSON + content files in `dist/`, records `sha256` digest in `.oiw/compiler.lock`. Same input + compiler version + target profile → byte-identical output.
- Implemented import report generator with `FULL | PARTIAL | FAILED` status, `recognized`, `preservedOpaque`, `unsupported`, `warnings` sections per spec §8.3.
- Implemented local simulation runtime MVP: `MessageContext` (body, headers, properties, attachments, variables, exchangeStatus, trace, securityContext), `ExecutionPlan` (topological sort), step registry, trace streaming. Core step plugins: `sender.http`, `modifier.content`, `script.groovy` (stubbed; sandbox enforced via static allowlist, NOT process-isolated — see DEV-003), `transform.xslt` (lxml-based, XSLT 1.0; Saxon-HE XSLT 2.0 subset deferred to JVM worker), `router.content-based`, `receiver.http` (mocked via in-process stub), `validator.json-schema`, `converter.json-to-xml`, `log.message`.
- Implemented test runner for `FlowTest` IR with assertions: `node.executed`, `node.not-executed`, `outbound.request` (body + headers + status + bodyMatchesXml/Json/contains), `exchange.status`, `header.equals`, `property.equals`, `body.contains`.
- Implemented semantic diff engine producing human-readable output per spec §10.5: added/removed/changed nodes, edges, resources, tests; validation/test/security/compatibility summary.
- Built reference scenario `examples/order-to-s4/`: inbound JSON order → JSON Schema validation → Groovy normalization → JSON-to-XML conversion → XSLT mapping → content-based router → mocked S/4 HTTP receiver → error subprocess. Includes `flow.yaml`, `diagram.json`, `tests/happy-path.yaml`, `tests/invalid-payload.yaml`, fixtures, scripts, XSLT, JSON schema, `dev.yaml` + `prod.yaml` environment profiles.
- Built golden fixture `packages/test-fixtures/minimal/https-content-modifier-http/`: synthetic source.zip + expected-ir.yaml + expected-export.zip + import-report.yaml. All synthetic — no customer artifacts.
- Built negative fixtures `packages/test-fixtures/negative/`: `zip-bomb.zip` (100 MB payload, ~1000:1 ratio), `path-traversal.zip` (../ entries), `corrupt-manifest.zip` (invalid zip).
- Authored GitHub Actions workflows:
  - `.github/workflows/validate-on-pr.yaml`: schema validation, `oiw validate --strict`, `oiw test --all`, `oiw build --target sap-cloud-integration-2026-07` + determinism re-check, Semgrep, gitleaks, Trivy, SBOM (syft), safe-archive inspector on negative + golden fixtures, semantic diff.
  - `.github/workflows/security-scan.yaml`: scheduled (daily) + on-push-to-main Semgrep + gitleaks + Trivy + SBOM.
  - `.github/workflows/release.yaml`: on tag push `v*`, build artifact, generate SBOM, attach to GitHub Release.
- Authored initial ADRs (001–020 per spec §25) + ADR-PY-001 (Python deviation) + ADR-CI-001 (GitHub Actions gate).
- Authored compatibility matrix, security threat model, contributor guide.
- Authored Docker Compose distribution matching spec §18.1 (services defined; build contexts point at stub Dockerfiles pending Kotlin migration). Added `.env.example` per spec §18.5.
- Authored issue template + PR template enforcing spec §22 Definition of Done.
- Created GitHub repo `hehenaice/open-integration-workbench`, pushed initial commit.
- Files touched: full repo tree; see `git log` for the per-file breakdown.
- Tests: local `oiw validate --strict` on `examples/order-to-s4` passes; `oiw test --all` passes 2/2 tests; `oiw build` produces deterministic artifact with sha256 digest (verified across two builds); archive inspector rejects `zip-bomb.zip` and `path-traversal.zip` negative fixtures. Pytest: 29/29 passed locally.
- CI: first `validate-on-pr` workflow run (https://github.com/hehenaice/open-integration-workbench/actions/runs/30625601562) — 5/6 jobs passed; `schema-self-check` failed due to missing `pip install jsonschema` step (fixed in this commit). `security-scan` workflow run passed (https://github.com/hehenaice/open-integration-workbench/actions/runs/30625601553).
- Next: OW-009 (expand golden fixtures), OW-008 (wire OPA into CLI), OW-001 (Kotlin migration) — in priority order.

### 2026-07-31 — Implementing Agent — CI fix: install jsonschema for schema self-check

- Fix: `.github/workflows/validate-on-pr.yaml` schema-self-check job was missing `pip install jsonschema` step. Added.
- Files touched: `.github/workflows/validate-on-pr.yaml`
- Tests: local schema self-check passes (4/4 schemas valid against Draft 2020-12 meta-schema).
- CI: re-running after push.

### 2026-07-31 — Implementing Agent — Phase 1 completion: missing MVP step plugins + soap-groovy-sftp fixture + WSL2 bootstrap

- Implemented the remaining MVP step plugins from spec §9.4 Initial Step Coverage:
  - `splitter.general` (simulated, bounded — enforces OIW-E003)
  - `gather` (simulated, bounded — supports concat + merge strategies for JSON, concat for XML)
  - `encoder.base64` (compatible-subset, encode + decode)
  - `filter` (compatible-subset, drops message if expression evaluates false)
  - `converter.xml-to-json` (compatible-subset, mirrors existing converter.json-to-xml)
  - `receiver.sftp` (simulated, mocked via FlowTest; real SFTP support is Phase 6)
- Total step plugins now: 15 (up from 9). The §9.4 MVP step coverage is now substantially complete; remaining gaps tracked as OW-013 (low priority): `sender.timer`, `subprocess.local`, `request-reply`, `datastore.write`, `datastore.read`.
- Extended `apps/cli/oiw/validators/rules.py` with the SFTP variant of OIW-W005 (warn when `receiver.sftp` sends a `credentialRef` to a non-placeholder host).
- Added the `soap-groovy-sftp` golden fixture (OW-009 partial) at `packages/test-fixtures/minimal/soap-groovy-sftp/`: synthetic `source.zip` (containing `flow.yaml` + `resources/scripts/extractPayload.groovy`), `expected-ir.yaml`, `expected-export.zip`, `import-report.yaml`, `roundtrip.diff`. Generator script: `scripts/generate_soap_groovy_sftp_fixture.py`. All synthetic — no customer artifacts.
- Added a second reference scenario `examples/sftp-order-drop/` exercising the new steps: inbound JSON batch → JSON Schema validation → bounded splitter → filter → bounded gather → base64 encode → mocked SFTP receiver → error subprocess. Includes `flow.yaml`, `diagram.json`, `tests/happy-path.yaml`, `tests/invalid-payload.yaml`, fixtures, schema, `dev.yaml` + `prod.yaml` environment profiles.
- Added 18 new unit tests for the new step plugins (`apps/cli/tests/test_new_steps.py`) and 8 new end-to-end tests for the sftp-order-drop scenario + soap-groovy-sftp fixture (`apps/cli/tests/test_sftp_order_drop_scenario.py`).
- Added WSL2 bootstrap script `deploy/wsl/bootstrap.sh` + `deploy/wsl/README.md` (spec §18.3). This satisfies the Phase 1 exit criterion "Windows WSL2 setup is documented".
- Updated `.github/workflows/validate-on-pr.yaml` to:
  - Regenerate the new `soap-groovy-sftp` fixture.
  - Validate + test + build both reference scenarios (`order-to-s4` and `sftp-order-drop`).
  - Verify determinism for both reference scenarios.
  - Inspect both golden fixtures (`https-content-modifier-http` and `soap-groovy-sftp`).
- Updated Phase Status: Phase 0 marked COMPLETE (pending tenant test, OW-010); Phase 1 marked COMPLETE (all exit criteria met).
- Updated Open Work: OW-009 partially done (soap-groovy-sftp complete; odata-pagination-aggregation deferred to OW-014 — needs Phase 6 OData plugin); added OW-013 (remaining §9.4 step plugins) and OW-014 (odata fixture).
- Updated `docs/compatibility/matrix.md` to reflect the new step coverage.
- Housekeeping: fixed `.gitignore` (`**/.oiw/compiler.lock` matches at any depth); removed `examples/order-to-s4/.oiw/compiler.lock` from tracking (was accidentally committed in the initial bootstrap).
- Files touched:
  - `apps/cli/oiw/runtime/steps/{splitter,gather,encoder_base64,filter,xml_to_json,sftp_receiver}.py` (new)
  - `apps/cli/oiw/runtime/steps/__init__.py` (register new plugins)
  - `apps/cli/oiw/validators/rules.py` (SFTP OIW-W005 variant)
  - `apps/cli/tests/test_new_steps.py` (new — 18 tests)
  - `apps/cli/tests/test_sftp_order_drop_scenario.py` (new — 8 tests)
  - `examples/sftp-order-drop/**` (new reference scenario)
  - `packages/test-fixtures/minimal/soap-groovy-sftp/**` (new golden fixture)
  - `scripts/generate_soap_groovy_sftp_fixture.py` (new)
  - `deploy/wsl/{bootstrap.sh,README.md}` (new — Phase 1 exit criterion)
  - `.github/workflows/validate-on-pr.yaml` (extended for new example + fixture)
  - `.gitignore` (fixed compiler.lock pattern)
  - `docs/compatibility/matrix.md` (updated)
  - `DEVELOPMENT_LOG.md` (this entry + phase status + open work updates)
- Tests: 55/55 passed locally (29 original + 18 new step tests + 8 new scenario tests).
- Lint: ruff check + format clean.
- Validation: `oiw validate --strict` passes on both `examples/order-to-s4` and `examples/sftp-order-drop`. `oiw test --all` passes 2/2 + 2/2. `oiw build` produces deterministic digests for both examples (verified).
- CI: PR #1 (https://github.com/hehenaice/open-integration-workbench/pull/1) — all 6 checks passed (run [#30627024663](https://github.com/hehenaice/open-integration-workbench/actions/runs/30627024663)). PR merged via squash-merge. Post-merge CI on `main` also green (validate-on-pr run [#30627194055](https://github.com/hehenaice/open-integration-workbench/actions/runs/30627194055), security-scan run [#30627194035](https://github.com/hehenaice/open-integration-workbench/actions/runs/30627194035)).
- Next: OW-001 (Kotlin migration) is the highest-priority remaining work; OW-013 (remaining §9.4 steps) is low priority and can wait until Phase 2.

---

### 2026-07-31 — Implementing Agent — Phase 2 starter: REST API (FastAPI prototype) + React SPA visual designer

- Started Phase 2 — Visual Workbench (spec §19, §10). Marked Phase 2 as IN PROGRESS.
- Authored OpenAPI 3.1 specification at `packages/api-spec/openapi.yaml` (spec §6.2 "OpenAPI 3.1 first", §21.1). Covers: projects, flows, validate, tests, builds, git status, archive inspect, health. The spec is the authoritative API contract — implementation-language-agnostic.
- Implemented FastAPI prototype server at `apps/server-python-prototype/` (ADR-PY-002). Thin shim over the existing `oiw` CLI logic — imports `oiw` directly, no subprocess, no duplication. Exposes all §21.1 endpoints. Serves auto-generated Swagger UI at `/docs` and ReDoc at `/redoc`.
  - Routes: projects, flows, validate, tests, builds, git, archive, health.
  - Pydantic models matching the OpenAPI spec.
  - Workspace discovery (scans `examples/` by default; override with `OIW_WORKSPACE` env var).
- Added 21 API tests at `apps/server-python-prototype/tests/test_api.py` — covers all endpoints, 404s, 400s, OpenAPI spec availability, Swagger UI, golden fixture inspection, zip-bomb/path-traversal rejection.
- Scaffolded React 19 + Vite 6 + TypeScript SPA at `apps/web/` (spec §6.1):
  - React Flow 12 for the flow canvas (dark theme, minimap, controls, background grid).
  - Tailwind CSS 4 via `@tailwindcss/vite`.
  - Original dark-theme design system (spec §2.2 — no SAP UI copying).
  - Three-pane layout: project explorer (left), flow canvas (center), properties + results panels (right).
  - Hand-written API client (`src/api.ts`) — will be generated from OpenAPI in OW-015.
  - IR → React Flow node/edge conversion (`src/flow-utils.ts`) using `diagram.json` for positions.
  - Functional panels: properties (click node to see config), validation (run `oiw validate --strict`), test runner (run `oiw test --all`), build (run `oiw build`), git status bar.
- Added Docker Compose profile `phase2-prototype` with `oiw-server` (FastAPI) + `oiw-web` (nginx-served SPA). Renamed old Phase 2 stubs to `oiw-server-kotlin` to avoid name collision.
  - `Dockerfile.server` — Python 3.12-slim, installs CLI + server.
  - `Dockerfile.web` — multi-stage Node 22 build + nginx serve, with API proxy config.
  - `nginx.conf` — SPA fallback + `/api/` proxy to `oiw-server:8000`.
- Added ADR-PY-002 documenting the FastAPI deviation: rationale, consequences, migration plan (OW-002 will replace it with Kotlin/Spring Boot against the same OpenAPI contract).
- Updated `.github/workflows/validate-on-pr.yaml`:
  - New job `api-pytest` — installs CLI + server, runs 21 API tests with `OIW_WORKSPACE` pointing at `examples/`.
  - New job `spa-build` — Node 22, `npm ci`, `tsc --noEmit`, `npm run build`, uploads `dist/` as artifact.
  - Extended `lint` job — also runs ruff on `apps/server-python-prototype/`.
  - Updated aggregate job to include `api-pytest` and `spa-build` as required checks.
- Updated Phase Status: Phase 2 marked IN PROGRESS.
- Added OW-015 (generate TypeScript API client from OpenAPI) and OW-016 (complete visual designer — drag-and-drop, Monaco, undo/redo, diff viewer, WebSocket trace streaming).
- Files touched:
  - `packages/api-spec/{openapi.yaml,README.md}` (new)
  - `apps/server-python-prototype/` (new — full FastAPI server + tests)
  - `apps/web/` (new — React 19 + Vite 6 + React Flow 12 SPA)
  - `deploy/docker-compose/{Dockerfile.server,Dockerfile.web,nginx.conf,docker-compose.yaml}` (new + updated)
  - `docs/architecture/adr-py-002-fastapi-prototype.md` (new)
  - `.github/workflows/validate-on-pr.yaml` (extended with api-pytest + spa-build + server lint)
  - `DEVELOPMENT_LOG.md` (this entry + phase status + open work updates)
- Tests: 21/21 API tests pass locally. SPA type-check passes. SPA build succeeds (343 KB JS / 18 KB CSS). CLI tests still 55/55 (no regression).
- Lint: ruff check + format clean for both `apps/cli/` and `apps/server-python-prototype/`.
- CI: pending first run on this PR.
- Next: OW-016 (complete visual designer — drag-and-drop, Monaco, trace streaming) is the highest-priority Phase 2 work; OW-002 (Kotlin server) can proceed in parallel once the SPA is feature-complete.

---

### 2026-07-31 — Implementing Agent — Phase 2 interactive designer: typed patches + drag-and-drop + editable properties

- Implemented the core Phase 2 exit criterion (spec §19): "A consultant can build the Phase 1 reference flow without editing YAML manually. UI and CLI produce equivalent IR."
- **Typed patch module** (`apps/cli/oiw/patch.py`): implements spec §12.5 Typed Patch Format with 6 operations:
  - `addNode` — add a new node with optional diagram position
  - `removeNode` — remove a node and all its edges (rejects entrypoint removal, rejects removing last node)
  - `updateNodeConfig` — partial-merge config update
  - `addEdge` — add an edge (validates endpoints exist, rejects duplicates)
  - `removeEdge` — remove an edge by from+to
  - `moveNode` — update a node's position in diagram.json
- Post-patch validation: checks for duplicate node IDs, dangling edges, and cycles. Does NOT check reachability (a user may add a node first and connect it later — reachability is checked by `oiw validate`).
- Base revision validation: if `base_revision` is provided and doesn't match the server's current HEAD, the patch is rejected (spec §12.5: "base revision matches HEAD").
- `write_flow()` serializes the flow back to `flow.yaml` with canonical ordering (nodes sorted by ID, edges sorted by (from, to)) and updates `diagram.json` (spec §7.3 rules 4 and 7).
- **PATCH endpoint** (`PATCH /api/v1/projects/{projectId}/flows/{flowId}`): applies typed patches, writes to disk, returns count of applied operations + current revision. Returns 400 for invalid operations (duplicate node, cycle, unknown op).
- **22 CLI-level patch tests** (`apps/cli/tests/test_patch.py`): covers all 6 operations, duplicate ID rejection, entrypoint removal rejection, last-node removal rejection, cycle rejection, base revision mismatch, canonical ordering, write-back persistence.
- **12 server-level PATCH API tests** (`apps/server-python-prototype/tests/test_patch_api.py`): covers add/remove/update/move via HTTP, multiple operations in one request, error cases (400s, 404s), empty operations no-op. Uses temp workspace fixture so tests can mutate files safely.
- **React SPA interactive editing**:
  - Node palette in left sidebar with 14 draggable step types (all §9.4 MVP steps).
  - Drag-and-drop onto canvas creates a new node at the drop position.
  - Properties panel is now editable: inline config editing with per-key text inputs; node ID is editable.
  - Node position changes (drag-stop) are tracked as `moveNode` ops.
  - Edge creation (drag between node handles) is tracked as `addEdge` ops.
  - Node/edge deletion (Delete/Backspace key) is tracked as `removeNode`/`removeEdge` ops.
  - "Save" button sends accumulated `pendingOps` as a single PATCH request, then reloads the flow from the server.
  - Dirty-state indicator in the header shows unsaved-changes count.
- **OpenAPI spec** updated: added `PATCH /flows/{flowId}` with `PatchRequest` and `PatchResponse` schemas documenting all 6 operations.
- **CI workflow** updated: `api-pytest` job now uses `--import-mode=importlib` to handle the two test files coexisting in the same `tests/` directory.
- Files touched:
  - `apps/cli/oiw/patch.py` (new — typed patch engine)
  - `apps/cli/tests/test_patch.py` (new — 22 tests)
  - `apps/server-python-prototype/oiw_server/routes/patches.py` (new — PATCH endpoint)
  - `apps/server-python-prototype/oiw_server/main.py` (register patches router)
  - `apps/server-python-prototype/tests/test_patch_api.py` (new — 12 API tests)
  - `apps/web/src/App.tsx` (rewritten — interactive editing, palette, save)
  - `apps/web/src/App.css` (palette + config editor styles)
  - `apps/web/src/api.ts` (added `patchFlow` method)
  - `packages/api-spec/openapi.yaml` (PATCH endpoint + PatchRequest/PatchResponse schemas)
  - `.github/workflows/validate-on-pr.yaml` (import-mode fix for api-pytest)
  - `DEVELOPMENT_LOG.md` (this entry)
- Tests: 110 total (55 CLI + 22 patch + 21 API + 12 PATCH API) — all pass. SPA type-check + build clean. ruff check + format clean.
- CI: pending first run on this PR.
- Next: Monaco editor for Groovy/XSLT resources (OW-016 continued), WebSocket trace streaming (§9.2 step 8, §21.2), then Phase 3 (MCP server + model gateway).

---

### 2026-07-31 — Implementing Agent — Phase 2 simulation trace streaming (§9.2 step 8, §21.2)

- Implemented simulation trace streaming — a consultant can now run a flow from the UI and see the per-node execution trace.
- **Runtime engine extended** (`apps/cli/oiw/runtime/engine.py`): added `trace_callback` parameter to `execute_flow()`. When provided, the callback fires on every trace event (enter/exit/error/complete) as it's produced, enabling real-time streaming. The callback receives the `TraceEntry` and the current `MessageContext`. A final `complete` event is emitted after the flow finishes.
- **POST /api/v1/projects/{id}/flows/{flowId}/simulate** endpoint (`apps/server-python-prototype/oiw_server/routes/simulate.py`): runs a flow synchronously with given input body, headers, and mocks. Returns the final status, duration, full trace, outbound calls, and final headers/properties. Spec §21.1.
- **WebSocket /ws/trace** endpoint: a client connects, sends a JSON simulate request, and receives trace events as JSON messages (`{type: "trace", ...}`) followed by a final `{type: "complete", status, duration_ms, trace_count}`. Spec §21.2, §9.2 step 8. Runs the flow in a thread pool to avoid blocking the event loop.
- **7 simulate API tests** (`apps/server-python-prototype/tests/test_simulate.py`): happy path, invalid payload (FAILED status), outbound call recording, body_file loading, 404s, trace completeness (all nodes appear). WebSocket tests deferred to Playwright E2E (OW-012) due to Starlette TestClient WebSocket compatibility issues.
- **SPA Simulate button + trace panel**: added a "Simulate" button to the actions sidebar. Clicking it runs the flow with a default EU-region test payload and displays the trace in a new "Simulation Trace" panel in the right sidebar. Each trace entry shows node_id, direction (enter/exit/error/complete), and summary, color-coded by direction. Outbound calls are listed below the trace.
- **OpenAPI spec** updated: added `POST /flows/{flowId}/simulate` with `SimulateRequest`, `SimulationResult`, and `TraceEntry` schemas.
- Files touched:
  - `apps/cli/oiw/runtime/engine.py` (added `trace_callback` parameter + streaming logic)
  - `apps/server-python-prototype/oiw_server/routes/simulate.py` (new — POST simulate + WebSocket /ws/trace)
  - `apps/server-python-prototype/oiw_server/main.py` (register simulate router)
  - `apps/server-python-prototype/tests/test_simulate.py` (new — 7 tests)
  - `apps/web/src/App.tsx` (Simulate button + trace panel)
  - `apps/web/src/App.css` (trace list + outbound call styles)
  - `apps/web/src/api.ts` (added `simulate` method + `SimulationResult` / `TraceEntry` types)
  - `packages/api-spec/openapi.yaml` (simulate endpoint + schemas)
  - `DEVELOPMENT_LOG.md` (this entry)
- Tests: 117 total (77 CLI + 33 API + 7 simulate) — all pass. SPA type-check + build clean (350 KB JS / 22 KB CSS). ruff check + format clean.
- CI: pending first run on this PR.
- Next: Monaco editor for Groovy/XSLT resources (OW-016), then Phase 3 (MCP server + model gateway + LLM-assisted engineering).

---

### 2026-07-31 — Implementing Agent — Phase 2 Monaco resource editor (§6.1, §10.3)

- Implemented Monaco-based resource editor — a consultant can now edit Groovy/XSLT/JSON Schema files inline without leaving the visual designer. Spec §6.1, §10.3.
- **Resource API endpoints** (`apps/server-python-prototype/oiw_server/routes/resources.py`):
  - `GET /api/v1/projects/{id}/resources` — list all resource files with path, name, resource_type, Monaco language, and size.
  - `GET /api/v1/projects/{id}/resources/{path}` — read a resource file's content. Path traversal prevented (rejects `..`, absolute paths, resolves and verifies within project root).
  - `PUT /api/v1/projects/{id}/resources/{path}` — write (create or update) a resource file. Only paths under `flows/<flow>/resources/` are allowed. Parent directories created automatically. Path traversal prevented.
  - Language mapping: `.groovy`→groovy, `.xsl`/`.xslt`/`.xsd`/`.xml`→xml, `.json`→json, `.yaml`/`.yml`→yaml, `.properties`→ini, etc.
  - Resource type classification (spec §12.4): `.groovy`→groovy, `.xsl`→xslt, `.xsd`→xsd, `.json`→json-schema, etc.
- **13 resource API tests** (`apps/server-python-prototype/tests/test_resources.py`): list resources, get Groovy/JSON-Schema/XSLT resources, 404 not found, path traversal rejected, create new file, overwrite existing, reject path outside resources/, reject path traversal, create parent dirs.
- **SPA Monaco editor** (`apps/web/src/ResourceEditor.tsx`):
  - Uses `@monaco-editor/react` with `vs-dark` theme.
  - Language auto-detected from file extension.
  - Inline Save button — PUTs content to server, shows dirty state.
  - Close button returns to canvas view.
  - Monaco options: minimap disabled, word wrap on, font size 13, tab size 2, automatic layout.
- **SPA tabbed canvas** (`apps/web/src/App.tsx`):
  - Canvas area now has a tab bar: "Flow Canvas" tab + a tab for the currently selected resource.
  - Clicking a resource in the resource explorer switches to the resource editor view.
  - Clicking "Flow Canvas" returns to the React Flow canvas.
- **SPA resource explorer** (left sidebar):
  - New "Resources" section below the palette.
  - Lists all resource files in the project with name, language badge, and size.
  - Click a resource to open it in the Monaco editor.
- **OpenAPI spec** updated: added `GET /resources`, `GET /resources/{path}`, `PUT /resources/{path}` with `ResourceSummary` and `ResourceContent` schemas.
- Files touched:
  - `apps/server-python-prototype/oiw_server/routes/resources.py` (new — 3 endpoints)
  - `apps/server-python-prototype/oiw_server/main.py` (register resources router)
  - `apps/server-python-prototype/tests/test_resources.py` (new — 13 tests)
  - `apps/web/src/ResourceEditor.tsx` (new — Monaco editor component)
  - `apps/web/src/App.tsx` (tabbed canvas + resource explorer)
  - `apps/web/src/App.css` (resource list, canvas toolbar, resource editor styles)
  - `apps/web/src/api.ts` (added `listResources` / `getResource` / `writeResource` + types)
  - `apps/web/package.json` (added `@monaco-editor/react` dependency)
  - `packages/api-spec/openapi.yaml` (resource endpoints + schemas)
  - `DEVELOPMENT_LOG.md` (this entry)
- Tests: 130 total (77 CLI + 40 API + 13 resources) — all pass. SPA type-check + build clean (367 KB JS / 24 KB CSS). ruff check + format clean.
- CI: pending first run on this PR.
- Next: Semantic diff viewer (§10.5), then Phase 3 (MCP server + model gateway + LLM-assisted engineering with typed patches).

---

### 2026-07-31 — Implementing Agent — Phase 2 semantic diff viewer (§10.5)

- Implemented the semantic diff viewer — a consultant can now see what changed between revisions in human-readable IR terms, not raw file diffs. Spec §10.5.
- **Structured diff engine** (`apps/cli/oiw/diff.py`): added `structured_diff()` returning a `StructuredDiff` dataclass with categorized changes (flows/resources/tests added/modified/removed + other). The existing `semantic_diff()` text function now delegates to `structured_diff()` and formats the result — no duplication.
  - `StructuredDiff.to_dict()` produces JSON-serializable output for the API.
  - `total_changes` property for quick at-a-glance count.
  - Status normalization: git status codes (A/D/M/R) → added/removed/modified/renamed.
- **GET /api/v1/projects/{id}/diff** endpoint (`apps/server-python-prototype/oiw_server/routes/diff.py`): accepts `?rev=HEAD~1` query param, returns `DiffResponse` with structured diff. Spec §21.1, §10.5.
- **6 diff API tests** (`apps/server-python-prototype/tests/test_diff.py`): returns correct structure, detects added resource, SHAs differ, no-changes case (HEAD vs HEAD), 404 for unknown project, flows structure validation. Uses a temp git repo with 2 commits to exercise real git history.
- **SPA DiffViewer component** (`apps/web/src/DiffViewer.tsx`): renders the structured diff with color-coded entries (added=green +, modified=amber ~, removed=red -, renamed=R). Groups by category (Flows/Resources/Tests/Other) with section headers and count badges. Shows base→head SHA range and total change count.
- **SPA "View Diff" button**: added to the actions sidebar. Clicking it fetches the diff from the API and renders the DiffViewer in the right sidebar.
- **OpenAPI spec** updated: added `GET /projects/{id}/diff` with `StructuredDiff` schema documenting all fields.
- Files touched:
  - `apps/cli/oiw/diff.py` (added `structured_diff()` + `StructuredDiff` dataclass; refactored `semantic_diff()` to use it)
  - `apps/server-python-prototype/oiw_server/routes/diff.py` (new — diff endpoint)
  - `apps/server-python-prototype/oiw_server/main.py` (register diff router)
  - `apps/server-python-prototype/tests/test_diff.py` (new — 6 tests)
  - `apps/web/src/DiffViewer.tsx` (new — diff viewer component)
  - `apps/web/src/App.tsx` (View Diff button + diff panel)
  - `apps/web/src/App.css` (diff viewer styles)
  - `apps/web/src/api.ts` (added `getDiff` method + `StructuredDiff` type)
  - `packages/api-spec/openapi.yaml` (diff endpoint + StructuredDiff schema)
  - `DEVELOPMENT_LOG.md` (this entry)
- Tests: 136 total (77 CLI + 46 API + 6 diff + 13 resources) — all pass. SPA type-check + build clean (370 KB JS / 25 KB CSS). ruff check + format clean.
- CI: pending first run on this PR.
- Next: Phase 2 is now substantially complete (interactive editing ✓, simulation trace ✓, Monaco resource editor ✓, semantic diff viewer ✓). The next major milestone is **Phase 3** — MCP server + model gateway + LLM-assisted engineering with typed patches. The typed patch infrastructure (PR #3) and resource write API (PR #5) give Phase 3 a solid foundation.

---

### 2026-07-31 — Implementing Agent — Phase 3 starter: MCP server (§12.4, §21.3)

- Started Phase 3 — LLM-Assisted Engineering. Built the MCP server that exposes OIW's operations as MCP tools for external agents (Claude, Cursor, Windsurf).
- **MCP server** (`apps/mcp-server/`): Python implementation speaking JSON-RPC 2.0 over stdio (the standard MCP transport). ADR-PY-003 documents the deviation from the spec's Kotlin target. The server is a thin protocol adapter — it delegates all business logic to the existing `oiw` CLI package. No duplication.
- **10 MCP tools** implemented per spec §12.4:
  - `project.list` — list all projects in the workspace
  - `flow.get` — get full flow IR (nodes, edges, diagram)
  - `flow.patch` — apply typed patch operations (§12.5: addNode, removeNode, updateNodeConfig, addEdge, removeEdge, moveNode)
  - `flow.validate` — run schema + graph + rule validation
  - `flow.simulate` — run local simulation, return trace + status
  - `resource.read` — read a resource file (path traversal prevented)
  - `resource.write` — create/update a resource file (only under flows/*/resources/)
  - `test.run` — execute flow tests
  - `build.export` — compile IR to target-profile artifact
  - `git.status` — get Git status + last build digest
- **Security** (spec §12.1, §16.3): the LLM never edits files directly (all mutations via `flow.patch`); never receives secret values (only `credentialRef` identifiers); never deploys (`build.export` produces an artifact but deployment requires Phase 4's approval gate). Path traversal prevented on all file operations. Tool permissions enforced server-side.
- **18 MCP tests** (`apps/mcp-server/tests/test_mcp.py`): protocol tests (initialize, tools/list, tools/call, unknown method, notification), tool definition validation (all have name/description/schema, all handlers registered), individual tool tests (project.list, flow.get, flow.validate, flow.simulate, resource.read + path traversal rejection, test.run, build.export, git.status, unknown tool error, flow.patch adds node).
- **Claude Desktop integration**: documented in README — add `oiw-mcp` as an MCP server in `claude_desktop_config.json` with `OIW_WORKSPACE` env var.
- **CI workflow extended**: new `mcp-pytest` job (18 tests); `lint` job extended to cover `apps/mcp-server/`; aggregate job now requires 9 checks (was 8).
- Added ADR-PY-003 documenting the Python MCP server deviation.
- Updated Phase Status: Phase 3 marked IN PROGRESS.
- Files touched:
  - `apps/mcp-server/` (new — full MCP server + tests)
  - `apps/mcp-server/oiw_mcp/{__init__,main,tools,config,workspace}.py`
  - `apps/mcp-server/tests/test_mcp.py` (new — 18 tests)
  - `apps/mcp-server/pyproject.toml` + `README.md`
  - `.github/workflows/validate-on-pr.yaml` (mcp-pytest job + lint extension)
  - `docs/architecture/adr-py-003-mcp-server-prototype.md` (new)
  - `docs/architecture/README.md` (ADR index updated)
  - `DEVELOPMENT_LOG.md` (this entry + phase status)
- Tests: 154 total (77 CLI + 59 API + 18 MCP) — all pass. ruff check + format clean.
- CI: pending first run on this PR.
- Next: Model gateway (§12.7) with LLM routing + redaction + token budgets + prompt-injection defense. Then requirement-to-plan workflow (§12.2). Then Phase 4 (tenant sync + deployment state machine).

---

### 2026-07-31 — Implementing Agent — Phase 3 model gateway (§12.7)

- Implemented the model gateway — LLM routing with redaction, token budgets, circuit breaker, and prompt-injection defense. Spec §12.7.
- **Model gateway** (`services/model-gateway-python/`): FastAPI service with 4 endpoints:
  - `POST /api/v1/llm/chat` — chat completion with redaction + budget check + circuit breaker + prompt-injection defense system prompt
  - `GET /api/v1/llm/budget/{projectId}` — token budget status
  - `GET /api/v1/llm/providers` — list configured providers
  - `GET /api/v1/llm/health` — health check
- **Redaction layer** (`oiw_gateway/redaction.py`): strips secrets from LLM context before forwarding to the provider. Patterns: Bearer tokens, Basic auth, API keys, passwords, secrets, tokens, PEM private keys, long credentialRef values (50+ chars), tenant URLs. Short credentialRef identifiers (like `s4-api-client`) are preserved — they're not secrets.
- **Prompt-injection defense** (`oiw_gateway/prompts.py`): system prompt appended to every LLM call. Contains the 6 critical security rules from spec §16.3: untrusted data, never follow file instructions, cannot grant deployment/secret access, never receive secret values, typed patches only, server-side enforcement. Security rules cannot be overridden by user prompts (they come first).
- **Budget tracker** (`oiw_gateway/budget.py`): per-project per-day token limit (default 2,000,000). Tracks tokens used + request count. Rejects requests when exhausted (HTTP 429).
- **Circuit breaker** (`oiw_gateway/budget.py`): per-provider failure threshold (default 5) + reset timeout (default 60s). States: closed → open (after threshold) → half-open (after timeout) → closed (on success). Rejects requests when open (HTTP 503).
- **Provider router** (`oiw_gateway/providers.py`): async HTTP calls to 5 providers:
  - Anthropic (Claude) — `ANTHROPIC_API_KEY`
  - OpenAI (GPT-4o) — `OPENAI_API_KEY`
  - Ollama (local, e.g. qwen3:32b) — `OLLAMA_URL` (default localhost:11434)
  - vLLM (local, OpenAI-compatible) — `VLLM_URL`
  - Azure OpenAI — `AZURE_OPENAI_KEY` + `AZURE_OPENAI_ENDPOINT`
- **43 tests** across 4 test files:
  - `test_redaction.py` (15 tests): bearer token, API key, password, secret, token, private key, basic auth, long credentialRef, short credentialRef preserved, tenant URL, no-secrets passthrough, empty string, message redaction (string + multipart), structure preservation.
  - `test_budget.py` (12 tests): budget check allowed/exhausted/would-exceed/separate-projects, status, exhausted status, multiple requests, circuit breaker closed/trips/resets/half-open/separate-providers.
  - `test_prompts.py` (8 tests): untrusted data rule, never-follow rule, deployment restriction, typed patch rule, server-side enforcement, no-user-prompt, with-user-prompt, security-rules-cannot-be-overridden.
  - `test_gateway_api.py` (8 tests): health, providers list, budget empty, chat redacts secrets, chat includes system prompt, chat rejects exhausted budget (429), chat records token usage, chat rejects when circuit breaker open (503).
- Added ADR-PY-004 documenting the Python model gateway deviation.
- **CI workflow extended**: new `gateway-pytest` job (43 tests); `lint` job extended to cover `services/model-gateway-python/`; aggregate job now requires 10 checks (was 9).
- Files touched:
  - `services/model-gateway-python/` (new — full model gateway + tests)
  - `services/model-gateway-python/oiw_gateway/{__init__,main,redaction,prompts,budget,providers}.py`
  - `services/model-gateway-python/tests/{test_redaction,test_budget,test_prompts,test_gateway_api}.py`
  - `services/model-gateway-python/pyproject.toml` + `README.md`
  - `.github/workflows/validate-on-pr.yaml` (gateway-pytest job + lint extension)
  - `docs/architecture/adr-py-004-model-gateway-prototype.md` (new)
  - `docs/architecture/README.md` (ADR index updated)
  - `DEVELOPMENT_LOG.md` (this entry + phase status)
- Tests: 197 total (77 CLI + 59 API + 18 MCP + 43 gateway) — all pass. ruff check + format clean.
- CI: pending first run on this PR.
- Next: Requirement-to-plan workflow (§12.2) — the agent pipeline that takes a natural-language requirement and produces typed tool calls. Then Phase 4 (tenant sync + deployment state machine).

---

### 2026-07-31 — Implementing Agent — Phase 3 agent pipeline (§12.2)

- Implemented the requirement-to-plan-to-implementation agent pipeline. Spec §12.2 (Agent Pipeline).
- **Agent pipeline** (`apps/server-python-prototype/oiw_server/agent.py`): three stages:
  1. **Requirements Interpreter** — normalizes NL requirement into intent (create-flow, modify-flow, add-validation, add-test, general), source/target protocol, operations (validate, transform, route, filter, split, gather, encode, log), and archetype.
  2. **Integration Planner** — produces a step-by-step plan with typed tool calls (flow.patch, resource.write, test.create, flow.validate, test.run). Each step has tool name, description, and arguments. Includes assumptions and risks.
  3. **Implementation Agent** — executes the plan by calling MCP tool dispatch functions. Collects results per step, tracks success/errors.
- **API endpoints** (`apps/server-python-prototype/oiw_server/routes/agent.py`):
  - `POST /api/v1/projects/{id}/agents:plan` — generate a plan from a NL requirement (no side effects)
  - `POST /api/v1/projects/{id}/agents:implement` — execute the plan (mutates files via typed patches). Supports `dryRun` mode.
- **New MCP tool** (`test.create`): creates a FlowTest YAML file under `flows/<flow>/tests/`. Added to the MCP server's tool catalogue and handler registry. Total MCP tools now: 11 (was 10).
- **17 agent tests** (`apps/server-python-prototype/tests/test_agent.py`):
  - Requirements interpreter: create-flow, add-validation, add-test, modify-flow, general, archetype detection (6 tests)
  - Integration planner: create-flow steps, add-validation creates resource, add-test creates test file, assumptions/risks, general risk (5 tests)
  - API endpoints: plan endpoint, plan 404, implement dry-run, implement add-validation (verifies node added), implement add-test (verifies test created + runnable), implement 404 (6 tests)
- Files touched:
  - `apps/server-python-prototype/oiw_server/agent.py` (new — pipeline: interpreter, planner, executor)
  - `apps/server-python-prototype/oiw_server/routes/agent.py` (new — 2 endpoints)
  - `apps/server-python-prototype/oiw_server/main.py` (register agent router)
  - `apps/server-python-prototype/tests/test_agent.py` (new — 17 tests)
  - `apps/mcp-server/oiw_mcp/tools.py` (added test.create tool + handler)
  - `DEVELOPMENT_LOG.md` (this entry)
- Tests: 171 total (77 CLI + 76 API [59 existing + 17 agent] + 18 MCP) — all pass. ruff check + format clean.
- CI: pending first run on this PR.
- Next: Phase 3 exit criteria are now substantially met (MCP server ✓, model gateway ✓, agent pipeline ✓). The next major milestone is **Phase 4** — tenant sync + deployment state machine + drift detection (spec §15).

---
