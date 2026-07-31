# Open Integration Workbench (OIW)

**An open-source, local-first engineering workbench and compatibility toolchain for building, testing, reviewing, versioning, and deploying integration content intended for SAP Cloud Integration.**

> **Not affiliated with or endorsed by SAP.**
> Compatible with selected SAP Cloud Integration artifact formats. Local simulation of supported integration semantics.

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![CI: Validate PR](https://github.com/hehenaice/open-integration-workbench/actions/workflows/validate-on-pr.yaml/badge.svg)](https://github.com/hehenaice/open-integration-workbench/actions/workflows/validate-on-pr.yaml)
[![Security Scan](https://github.com/hehenaice/open-integration-workbench/actions/workflows/security-scan.yaml/badge.svg)](https://github.com/hehenaice/open-integration-workbench/actions/workflows/security-scan.yaml)
[![Status: Phase 0/1](https://img.shields.io/badge/Status-Phase%200%2F1%20Bootstrap-orange.svg)](DEVELOPMENT_LOG.md)

## What this is

OIW treats SAP Cloud Integration (CPI) development as a software-engineering discipline rather than a tenant-bound configuration exercise:

- **Git is the source of truth.** Integration content lives as normalized text and resources in a Git repository. Generated SAP-compatible packages are build outputs, not primary source.
- **Canonical Intermediate Representation (IR).** All authoring surfaces (UI, CLI, LLM tools) operate exclusively on a versioned IR. SAP import/export is a compiler boundary — no proprietary structures leak into the authoring layer.
- **Explicit fidelity.** Every component declares one of `authoring-only | simulated | compatible-subset | tenant-required | unsupported`. We never claim runtime equivalence we cannot prove.
- **Human-controlled AI.** LLMs propose typed patches. They never mutate repositories or deploy without policy checks and explicit human approval.
- **Local-first and offline-capable.** The workbench runs without an internet connection except for LLM calls, schema downloads, tenant sync, and remote Git.
- **Deterministic builds.** Same project revision + compiler version + dependency lockfile + target profile → same artifact bytes.

## Current status

Phase 0/1 bootstrap is in progress. See [`DEVELOPMENT_LOG.md`](DEVELOPMENT_LOG.md) — the single source of truth for project state, decisions, deviations, and next steps.

Implemented so far:
- Monorepo structure per spec §20.
- IR JSON Schemas (`oiw.yaml`, `flow.yaml`, `FlowTest`, `EnvironmentProfile`) per spec §7.
- `oiw` CLI: `init`, `validate`, `test`, `build`, `diff`, `import`, `git status` per spec §11.1 / §19 Phase 1.
- Semantic graph validator with rule codes `OIW-E001..E007`, `OIW-W001..W012` per spec §14.1.
- Safe archive inspector with zip-bomb and path-traversal defenses per spec §8.2.
- Deterministic export compiler producing a manifest + digest per spec §8.4.
- Local simulation runtime MVP: `MessageContext`, `ExecutionPlan`, core step plugins per spec §9.
- Reference scenario `examples/order-to-s4/` per spec §26.3.
- Docker Compose distribution scaffold per spec §18.1.
- GitHub Actions: `validate-on-pr.yaml`, `security-scan.yaml`, `release.yaml` per spec §14.4.

Planned but not yet implemented: visual designer (Phase 2), MCP server + model gateway (Phase 3), tenant connectivity (Phase 4), Experience Memory Graph (Phase 5).

## Quick start

### Prerequisites

- Python 3.11+ (Phase 0/1 implementation language; Kotlin/Spring Boot migration tracked in `DEVELOPMENT_LOG.md` ADR-PY-001)
- Git 2.40+
- (Optional) Docker 24+ and Docker Compose v2 for the full local stack

### Install the CLI (development mode)

```bash
git clone https://github.com/hehenaice/open-integration-workbench.git
cd open-integration-workbench
pip install -e apps/cli
```

### Try the reference scenario

```bash
cd examples/order-to-s4
oiw validate --strict
oiw test --all
oiw build --target sap-cloud-integration-2026-07
oiw diff HEAD~1
```

### Start a new project

```bash
oiw init my-integration --archetype api-to-erp
cd my-integration
oiw validate
```

## Repository layout

```
open-integration-workbench/
├── DEVELOPMENT_LOG.md          # Single source of truth (read this first)
├── apps/                       # User-facing applications
│   ├── cli/                    # oiw CLI (Phase 1: Python; future: Kotlin/picocli)
│   ├── web/                    # React SPA visual designer (Phase 2)
│   ├── server/                 # Kotlin/Spring Boot modular monolith (Phase 2+)
│   └── mcp-server/             # MCP protocol server (Phase 3)
├── services/                   # Background services
│   ├── runtime-worker/         # Java 21 isolated execution (Phase 2+)
│   ├── model-gateway/          # LLM routing + redaction (Phase 3)
│   └── emg-worker/             # Experience Memory Graph (Phase 5)
├── packages/                   # Reusable libraries
│   ├── ir-schema/              # JSON Schemas for the canonical IR
│   ├── semantic-diff/          # Diff engine
│   ├── policy-rules/           # OPA/Rego + Semgrep policies
│   └── test-fixtures/          # Golden import/export fixtures
├── plugins/                    # Step and adapter plugins (Phase 1+)
├── deploy/                     # Docker Compose, Helm, WSL bootstrap
├── docs/                       # ADRs, compatibility matrix, security, contributor guide
├── examples/order-to-s4/       # Reference end-to-end scenario
└── .github/workflows/          # CI: validate-on-pr, security-scan, release
```

See spec §20 for the full target structure.

## Legal boundaries

OIW is **not** a reproduction of SAP's proprietary product, runtime, source code, or branded UI. See spec §2 for the full list of mandatory prohibitions and `NOTICE` for the trademark statement.

Public language we use:
> "Compatible with selected SAP Cloud Integration artifact formats."
> "Local simulation of supported integration semantics."
> "Not affiliated with or endorsed by SAP."

## Contributing

Read [`DEVELOPMENT_LOG.md`](DEVELOPMENT_LOG.md) first — it captures the current phase, open work, and architectural decisions. Then read [`docs/contributor-guide/`](docs/contributor-guide/) and the relevant ADRs under [`docs/architecture/`](docs/architecture/).

Every PR must pass the `validate-on-pr` workflow: schema validation, `oiw validate --strict`, `oiw test --all`, `oiw build`, Semgrep, gitleaks, Trivy, and SBOM generation. See spec §22 for the Definition of Done.

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

## References

- [Experience Memory Graph: One-Shot Error Correction for Agents (Wang et al., 2026)](https://arxiv.org/abs/2607.13884)
- [SAP Cloud Integration documentation](https://help.sap.com/docs/cloud-integration)
- [Integration Flow Design Guidelines](https://help.sap.com/docs/cloud-integration/sap-cloud-integration/integration-flow-design-guidelines)
