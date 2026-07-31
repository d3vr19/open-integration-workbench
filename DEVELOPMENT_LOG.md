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
| Phase 0 — Research & Compatibility Probe | IN PROGRESS | Spec §19 | IR schemas, archive inspector, minimal import/export, golden fixture — substantially complete; manual tenant acceptance test deferred (no tenant available in dev environment) |
| Phase 1 — Git-Native Headless Core | IN PROGRESS | Spec §19 | CLI (`init`, `validate`, `test`, `build`, `diff`, `import`, `git status`), validator, semantic diff, compiler interface, Docker Compose — substantially complete |
| Phase 2 — Visual Workbench | NOT STARTED | Spec §19 | React Flow 12 + Monaco + Zustand; deferred until Phase 1 stable |
| Phase 3 — LLM-Assisted Engineering | NOT STARTED | Spec §19 | Model gateway + MCP server + typed patch tools; deferred |
| Phase 4 — Tenant Sync & CI/CD | NOT STARTED | Spec §19 | Deployment state machine, drift detection; deferred until local build correctness is proven |
| Phase 5 — Experience Memory Graph | NOT STARTED | Spec §19 | Trajectory recorder + graph matching + retrieval; deferred |
| Phase 6 — Compatibility Expansion | NOT STARTED | Spec §19 | Additional adapters (SFTP, SOAP, OData, IDoc, Mail, JMS, SuccessFactors, ProcessDirect); deferred |

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
| OW-009 | Expand golden fixture coverage: add `soap-groovy-sftp` and `odata-pagination-aggregation` minimal fixtures | Phase 1 | Medium | None |
| OW-010 | Manual tenant acceptance test against a real SAP CI dev tenant | Phase 0 exit | High (blocked) | Tenant access |
| OW-011 | Add `oiw agent review` GitHub Action step (Phase 3 dependency) | Phase 3 | Low | OW-004 |
| OW-012 | Add UI E2E tests with Playwright (10 critical journeys) | Phase 2 exit | Medium | OW-007 |

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

---
