# Open Integration Workbench (OIW)

**An open-source, local-first engineering workbench and compatibility toolchain for building, testing, reviewing, versioning, and deploying integration content intended for SAP Cloud Integration.**

> **Not affiliated with or endorsed by SAP.**
> Compatible with selected SAP Cloud Integration artifact formats. Local simulation of supported integration semantics.

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![CI: Validate PR](https://github.com/hehenaice/open-integration-workbench/actions/workflows/validate-on-pr.yaml/badge.svg)](https://github.com/hehenaice/open-integration-workbench/actions/workflows/validate-on-pr.yaml)
[![Security Scan](https://github.com/hehenaice/open-integration-workbench/actions/workflows/security-scan.yaml/badge.svg)](https://github.com/hehenaice/open-integration-workbench/actions/workflows/security-scan.yaml)
[![Status: Phase 3](https://img.shields.io/badge/Status-Phase%203%20(Substantially%20Complete)-green.svg)](DEVELOPMENT_LOG.md)
[![Tests: 315](https://img.shields.io/badge/Tests-315%20passing-brightgreen.svg)](https://github.com/hehenaice/open-integration-workbench/actions/workflows/validate-on-pr.yaml)

## What this is

OIW treats SAP Cloud Integration (CPI) development as a software-engineering discipline rather than a tenant-bound configuration exercise:

- **Git is the source of truth.** Integration content lives as normalized text and resources in a Git repository. Generated SAP-compatible packages are build outputs, not primary source.
- **Canonical Intermediate Representation (IR).** All authoring surfaces (UI, CLI, LLM tools) operate exclusively on a versioned IR. SAP import/export is a compiler boundary — no proprietary structures leak into the authoring layer.
- **Explicit fidelity.** Every component declares one of `authoring-only | simulated | compatible-subset | tenant-required | unsupported`. We never claim runtime equivalence we cannot prove.
- **Human-controlled AI.** LLMs propose typed patches. They never mutate repositories or deploy without policy checks and explicit human approval.
- **Local-first and offline-capable.** The workbench runs without an internet connection except for LLM calls, schema downloads, tenant sync, and remote Git.
- **Deterministic builds.** Same project revision + compiler version + dependency lockfile + target profile → same artifact bytes.

## Current status

Phases 0–3 are substantially complete. See [`DEVELOPMENT_LOG.md`](DEVELOPMENT_LOG.md) — the single source of truth for project state, decisions, deviations, and next steps.

### What's implemented

**Phase 0/1 — Git-Native Headless Core** (COMPLETE):
- `oiw` CLI: `init`, `validate`, `test`, `build`, `diff`, `import`, `git status`, `archive inspect`
- IR JSON Schemas (`oiw.yaml`, `flow.yaml`, `FlowTest`, `EnvironmentProfile`) per spec §7
- 15 step plugins (sender.http, modifier.content, script.groovy, transform.xslt, router, filter, converters, encoder, splitter, gather, receiver.http, receiver.sftp, validator.json-schema, log.message)
- Semantic graph validator with rule codes `OIW-E001..E007`, `OIW-W001..W012`
- Safe archive inspector (zip-bomb + path-traversal defense)
- Deterministic export compiler with sha256 digest
- Typed patch engine (6 operations: addNode, removeNode, updateNodeConfig, addEdge, removeEdge, moveNode)
- 2 reference scenarios + 2 golden fixtures + 3 negative fixtures
- Docker Compose + WSL2 bootstrap
- GitHub Actions CI (10 required checks)

**Phase 2 — Visual Workbench** (SUBSTANTIALLY COMPLETE):
- REST API (FastAPI prototype, OpenAPI 3.1 spec)
- React 19 + React Flow 12 SPA with dark theme
- Drag-and-drop node creation from palette
- Editable properties panel (inline config editing)
- Monaco editor for Groovy/XSLT/JSON Schema resources
- Simulation trace streaming (WebSocket + trace panel)
- Semantic diff viewer (structured diff with color-coded entries)
- Validate / Test / Build / Simulate / View Diff buttons
- Git status bar (branch, HEAD SHA, dirty flag, build digest)

**Phase 3 — LLM-Assisted Engineering** (SUBSTANTIALLY COMPLETE):
- MCP server (11 tools, JSON-RPC 2.0 over stdio) — works with Claude Desktop, Cursor, Windsurf
- Model gateway (redaction, token budgets, circuit breaker, prompt-injection defense, 5 LLM providers)
- Agent pipeline (requirement interpreter → integration planner → implementation agent)
- POST `/agents:plan` and POST `/agents:implement` endpoints
- **WP-04 complete**: LLM-driven agent pipeline (Tasks 1-7), trajectory recorder (Task 4),
  baseRevision enforcement (Task 6), agent evaluation harness (Task 8), co-pilot UI panel (Task 9)

### What's not yet implemented

- **Phase 4** (next): Tenant sync, deployment state machine, drift detection
- **Phase 5**: Experience Memory Graph (graph matching, retrieval) — requires Phase 4 deployment outcomes for honest reward vectors
- **Phase 6**: Additional adapters (SOAP, OData, IDoc, Mail, JMS, SuccessFactors)
- Kotlin/Spring Boot migration (currently Python prototypes with documented ADRs)
- JVM process-isolated runtime worker (security-critical for untrusted Groovy)
- Playwright E2E in CI (OW-026 — tests pass locally, not yet wired into GitHub Actions)
- OPA/Rego wired into CLI (runs in CI only)

## Quick start

### Prerequisites

- Python 3.11+ (implementation language; Kotlin migration tracked in ADR-PY-001)
- Node.js 22+ (for the SPA)
- Git 2.40+
- (Optional) Docker 24+ and Docker Compose v2 for the full local stack

### Install the CLI

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

### Start the visual designer

> **Security note:** The API server has **no authentication** in local mode (spec §16.2).
> It binds to `127.0.0.1` by default. Do not expose the API port to untrusted networks.
> Set `OIW_HOST=0.0.0.0` only in trusted team environments (auth not yet implemented — OW-005).

```bash
# Terminal 1: API server (binds to 127.0.0.1 by default)
pip install -e apps/cli -e apps/server-python-prototype -e apps/mcp-server
OIW_WORKSPACE=$(pwd)/examples uvicorn oiw_server.main:app --reload --port 8000

# Terminal 2: SPA
cd apps/web
npm install
npm run dev
# Open http://localhost:5173
```

### Use the MCP server with Claude Desktop

```bash
pip install -e apps/cli -e apps/mcp-server
```

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "oiw": {
      "command": "oiw-mcp",
      "env": { "OIW_WORKSPACE": "/path/to/projects" }
    }
  }
}
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
├── DEVELOPMENT_LOG.md              # Single source of truth (read this first)
├── apps/
│   ├── cli/                        # oiw CLI (Python; ADR-PY-001)
│   ├── web/                        # React 19 + React Flow 12 SPA
│   ├── server-python-prototype/    # FastAPI REST API (ADR-PY-002)
│   ├── server/                     # Kotlin/Spring Boot target (placeholder)
│   └── mcp-server/                 # MCP server (Python; ADR-PY-003)
├── services/
│   ├── model-gateway-python/       # LLM gateway (Python; ADR-PY-004)
│   ├── model-gateway/              # Kotlin target (placeholder)
│   ├── runtime-worker/             # JVM runtime worker target (placeholder)
│   └── emg-worker/                 # Experience Memory Graph (placeholder)
├── packages/
│   ├── ir-schema/                  # JSON Schemas for the canonical IR
│   ├── api-spec/                   # OpenAPI 3.1 spec
│   ├── policy-rules/               # OPA/Rego + Semgrep policies
│   └── test-fixtures/              # Golden import/export fixtures
├── deploy/                         # Docker Compose, Helm, WSL bootstrap
├── docs/                           # ADRs, compatibility matrix, security, contributor guide
├── examples/                       # Reference scenarios (order-to-s4, sftp-order-drop)
├── scripts/                        # Fixture generators
└── .github/workflows/              # CI: validate-on-pr (10 jobs), security-scan, release
```

See spec §20 for the full target structure.

## Testing

| Package | Tests | Description |
|---------|-------|-------------|
| `apps/cli` | 153 | CLI, validators, patch engine, runtime steps, archive safety, error subprocess, **agent pipeline** (WP-04 Tasks 1-7) |
| `apps/server-python-prototype` | 78 | REST API, PATCH endpoints, simulate, resources, diff, agent pipeline |
| `apps/mcp-server` | 20 | MCP protocol, 11 tools, baseRevision enforcement (WP-04 Task 6) |
| `services/model-gateway-python` | 43 | Redaction, budget, circuit breaker, prompts, API |
| `tests/agent_eval` | 19 | Agent evaluation harness (WP-04 Task 8): benchmarks, runner, metrics |
| `apps/web/e2e` | 2 | Playwright E2E: co-pilot suggest+apply, reject (WP-04 Task 9) |
| **Total** | **315** | 313 unit/integration + 2 E2E; all pass in CI |

CI runs 11 required checks: OIW validate+test+build, schema self-check, CLI pytest, API pytest, MCP pytest, gateway pytest, ruff lint, SPA build, DEVELOPMENT_LOG.md present, **agent-eval** (WP-04 Task 8).

## Legal boundaries

OIW is **not** a reproduction of SAP's proprietary product, runtime, source code, or branded UI. See spec §2 for the full list of mandatory prohibitions and `NOTICE` for the trademark statement.

Public language we use:
> "Compatible with selected SAP Cloud Integration artifact formats."
> "Local simulation of supported integration semantics."
> "Not affiliated with or endorsed by SAP."

## Contributing

Read [`DEVELOPMENT_LOG.md`](DEVELOPMENT_LOG.md) first — it captures the current phase, open work, and architectural decisions. Then read [`docs/contributor-guide/`](docs/contributor-guide/) and the relevant ADRs under [`docs/architecture/`](docs/architecture/).

Every PR must pass the `validate-on-pr` workflow (10 required checks). See spec §22 for the Definition of Done.

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

## References

- [Experience Memory Graph: One-Shot Error Correction for Agents (Wang et al., 2026)](https://arxiv.org/abs/2607.13884)
- [SAP Cloud Integration documentation](https://help.sap.com/docs/cloud-integration)
- [Integration Flow Design Guidelines](https://help.sap.com/docs/cloud-integration/sap-cloud-integration/integration-flow-design-guidelines)
