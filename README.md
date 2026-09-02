# Open Integration Workbench (OIW)

**An open-source, local-first engineering workbench and compatibility toolchain for building, testing, reviewing, versioning, and deploying integration content intended for SAP Cloud Integration.**

> **Not affiliated with or endorsed by SAP.**
> Compatible with selected SAP Cloud Integration artifact formats. Local simulation of supported integration semantics.

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![CI: Validate PR](https://github.com/hehenaice/open-integration-workbench/actions/workflows/validate-on-pr.yaml/badge.svg)](https://github.com/hehenaice/open-integration-workbench/actions/workflows/validate-on-pr.yaml)
[![Security Scan](https://github.com/hehenaice/open-integration-workbench/actions/workflows/security-scan.yaml/badge.svg)](https://github.com/hehenaice/open-integration-workbench/actions/workflows/security-scan.yaml)
[![Status: P6 Hands-Free Proof](https://img.shields.io/badge/Status-P6%20Hands--Free%20PROVEN-brightgreen.svg)](DEVELOPMENT_LOG.md)
[![Tests: 812](https://img.shields.io/badge/Tests-812%20passing-brightgreen.svg)](https://github.com/hehenaice/open-integration-workbench/actions/workflows/validate-on-pr.yaml)

## What this is

OIW treats SAP Cloud Integration (CPI) development as a software-engineering discipline rather than a tenant-bound configuration exercise:

- **Git is the source of truth.** Integration content lives as normalized text and resources in a Git repository. Generated SAP-compatible packages are build outputs, not primary source.
- **Canonical Intermediate Representation (IR).** All authoring surfaces (UI, CLI, LLM tools) operate exclusively on a versioned IR. SAP import/export is a compiler boundary — no proprietary structures leak into the authoring layer.
- **Explicit fidelity.** Every component declares one of `authoring-only | simulated | compatible-subset | tenant-required | unsupported`. We never claim runtime equivalence we cannot prove.
- **Human-controlled AI.** LLMs propose typed patches. They never mutate repositories or deploy without policy checks and explicit human approval.
- **Local-first and offline-capable.** The workbench runs without an internet connection except for LLM calls, schema downloads, tenant sync, and remote Git.
- **Deterministic builds.** Same project revision + compiler version + dependency lockfile + target profile → same artifact bytes.

## Current status

Phases 0–3 are substantially complete. WP-08 (Productize the Learning Loop) is in progress — **Track D GATE PASSED** (PR-1 through PR-8 done; UI work now authorized). **P6 hands-free proof LIVE (2026-09-02)**: a natural-language directive produced a working iFlow pair on the live BTP tenant — turbo-assembled, deployed, STARTED, message 200, MPL COMPLETED on both artifacts. **EMG fed with real experience**: the tenant catalog (600 running flows) is absorbed into the Experience Memory Graph; parity agreement is 100% on fresh oracle cases. **Self-improvement proven**: the first teacher-summons (JSON→XML conversion) was answered by live bisection, merged back as a piece + placement law — the same requirement now builds and runs autonomously (reward 1.0), and the learned chain auto-promotes to the EMG. See [`DEVELOPMENT_LOG.md`](DEVELOPMENT_LOG.md) — the single source of truth for project state, decisions, deviations, and next steps.

### What's implemented

**Phase 0/1 — Git-Native Headless Core** (COMPLETE):
- `oiw` CLI: `init`, `validate`, `test`, `build`, `diff`, `import`, `git status`, `archive inspect`, `emg status|reindex|report|provenance`, `tenant ping|list|artifacts|pull`
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
- **WP-04 complete**: LLM-driven agent pipeline (Tasks 1-7), trajectory recorder (Task 4), baseRevision enforcement (Task 6), agent evaluation harness (Task 8), co-pilot UI panel (Task 9)

**WP-08 — Productize the Learning Loop** (IN PROGRESS — PR-1 through PR-8 done; **Track D GATE PASSED → UI authorized**):
- **Durable EMG substrate (PR-1/A-001)**: `JsonlEmgStore` persists insights + task nodes + edges + manifest to `.oiw/emg/{manifest.yaml, insights.jsonl, tasks.jsonl, edges.jsonl}` with atomic writes. Manifest stamps `{backend, model, dim}`. Dim-mismatch protection (vectors from a different backend/dim are skipped, never mixed). Survives process restart.
- **CLI + server wiring (PR-3/A-003)**: `oiw emg status` (with `--json`) + `oiw emg reindex` (idempotent). FastAPI server loads persisted store on startup; all 3 EMG routes read from the durable store, fall back to in-memory test dict when not available. `/emg/stats` surfaces `embeddingBackend`/`embeddingModel`/`embeddingDim`/`storePath`/`compatible`.
- **Promotion persists (PR-3/A-004)**: `promote_seed_corpus(durable_store=..., persist=True)` writes PROJECT_APPROVED insights + their task nodes to the durable store. Backward-compatible.
- **Import parser fixes (PR-5/B-002)**: `parse_bpmn2_iflw()` classifies `<callActivity>` elements by their `<ifl:property><key>activityType</key>` block. `_ACTIVITY_TYPE_MAP` covers 20 SAP CI activityTypes (Enricher→modifier.content, Mapping→transform.xslt, JsonToXmlConverter→converter.json-to-xml, Script→script.groovy, DBstorage→datastore.write [tenant-required], etc.). Unknown types preserved as `unsupported_call_activities` with raw properties — NEVER silently dropped. Real-tenant before/after: 2 recognized components → 6 recognized.
- **Tenant pull → redact → persist (PR-7/C-001)**: `oiw tenant pull --persist` downloads an artifact, imports it, redacts the IR via the existing `Redactor`, writes `flow.yaml` + `import-report.yaml` + `metadata.yaml` (`provenance.source=tenant`, `tenantHash`, `isReal=true`, `license=customer-content`) under `packages/seed-corpus/artifacts/tenant-<pkg>-<art>/`. Optionally persists a TaskMemoryNode to the EMG store. Verified end-to-end against a live BTP tenant.
- **CodeJam corpus (PR-6/B-001+B-002+B-003)**: `scripts/ingest_codejam.py` walks the cloned SAP-samples CodeJam repo, finds ZIPs containing iFlows, parses each with the fixed parser, redacts, persists to `packages/seed-corpus/artifacts/codejam-*` + durable EMG store. 7 distinct iFlows ingested. Retrieval proof at `docs/emg/wp08-codejam-retrieval.yaml` — paraphrase retrieves at 0.61 similarity; unrelated SFTP requirement correctly retrieves nothing.
- **EmbeddingGemma-300m backend (PR-2/A-002)**: `GemmaEmbedder` (sentence-transformers + google/embeddinggemma-300m with Matryoshka dim truncation). Falls back to a deterministic hash-based pseudo-embedding when `sentence-transformers` is not installed — never crashes the caller. `create_embedder("auto"|"gemma"|"fastembed"|"openai"|"tfidf")` factory with auto-select chain. Install with `pip install 'oiw[embeddings]'`. CI stays on TF-IDF per WP-08 §10.
- **Tenant read-only adapter (Track 0)**: real `SapCiTenantAdapter` (~280 lines) replacing the NotImplementedError stub. HTTP Basic auth against `/api/v1`. `connect`, `list_packages`, `list_artifacts`, `download_artifact`, `get_artifact_version`, `get_artifact_digest`. Write ops stay NotImplementedError per WP-08 §C-004. `oiw tenant ping|list|artifacts|pull` CLI commands work end-to-end against a live BTP tenant.
- **Held-out proof PASSED (PR-8/Track D — THE GATE)**: Created `examples/held-out-order-async/` (NOT in CodeJam/tenant corpus). Ran the agent `--no-emg` (baseline: 0 plan steps, no EMG) vs `--emg` (3 plan steps, mechanics-first hit — EMG retrieved a CodeJam insight at confidence 0.35, LLM NOT needed). All 4 WP-08 D-003 pass criteria met: (1) real provenance (sap-codejam), (2) similarity 0.35 ≥ 0.3 threshold, (3) measurably better (mechanics-first hit + plan steps 0→3), (4) held-out not in store. Proof at `docs/emg/wp08-held-out-proof.yaml`. **UI work (PR-10/Track E) is now authorized.**

### What's not yet implemented

- **WP-08 PR-9 / Track D-004** (OW-031): optional tenant deploy of held-out package. Requires implementing `upload_package`/`deploy` (currently NotImplementedError per WP-08 §C-004).
- **WP-08 PR-10 / Track E** (OW-032): UI reads persisted store. Infrastructure ready (server loads store on startup, `/emg/stats` surfaces real counts + backend/dim/path); UI components themselves untouched. **Now authorized** — the Track D gate has passed.
- **WP-08 PR-2 follow-up** (OW-033): install EmbeddingGemma-300m in dev/tenant environments. The pseudo-embedding fallback (DEV-026) must be replaced with real Gemma in any environment doing real learning.
- **Phase 4 write path**: deployment state machine, drift detection (OW-005 — read-only adapter is done; write path deferred).
- **Phase 6**: additional adapters (JMS, SuccessFactors, ProcessDirect); SOAP/OData/IDoc/Mail receivers already simulated.
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

### Tenant integration (WP-08 Track 0 + C — read-only)

OIW now talks to live SAP Cloud Integration tenants (read-only) for inventory + artifact download. Configure via env vars:

```bash
export OIW_USE_REAL_TENANT=1
export OIW_TENANT_URL=https://<tenant>.it-cpi0XX.cfapps.<region>.hana.ondemand.com/api/v1
export OIW_TENANT_USER=S0026012658       # S-user for HTTP Basic auth
export OIW_TENANT_PASSWORD='...'

# Smoke test — list ≥ 1 package from the tenant
oiw tenant ping --profile btp --project examples/order-to-s4

# Inventory: list packages + their artifacts
oiw tenant list --top 50
oiw tenant artifacts --package <pkgId>

# Download a single artifact ZIP
oiw tenant pull --package <pkgId> --artifact <artId> --out tenant.zip

# Download + redact + persist to the seed corpus + EMG store (WP-08 PR-7/C-001)
oiw tenant pull --package <pkgId> --artifact <artId> \
  --out tenant.zip --persist --profile btp --project examples/order-to-s4
```

The `btp` profile (`examples/order-to-s4/environments/btp.yaml`) is the Basic-auth profile for the live BTP tenant. The adapter is **read-only** per WP-08 §C-004 ("the tenant is a library, not a scratchpad") — `upload_package`/`deploy`/`poll_deployment` raise `NotImplementedError`. Write path is deferred to Track D-004 (OW-031).

### Durable EMG store (WP-08 PR-1 through PR-3 — Track A)

The Experience Memory Graph now persists to disk:

```bash
# Show store path, backend, model, dim, insight/task/edge counts, compatibility
oiw emg status

# Re-embed every task node under a new backend (e.g. switch to Gemma after
# `pip install 'oiw[embeddings]'`). Idempotent — dedupes by task_id.
oiw emg reindex --backend gemma --model google/embeddinggemma-300m --dim 768

# Same status in JSON for programmatic consumers
oiw emg status --json
```

Store layout (under `$OIW_WORKSPACE/.oiw/emg/` or `./.oiw/emg/`):
- `manifest.yaml` — `{schemaVersion, embedding.backend, embedding.model, embedding.dim}`
- `insights.jsonl` — `InsightRecord` + promotion state
- `tasks.jsonl` — `TaskMemoryNode` with `requirementEmbedding` + `embeddingBackend`
- `edges.jsonl` — `CrossTaskEdge`

Atomic writes (temp-file-then-rename); dim-mismatch protection (vectors from a different backend/dim are skipped, never mixed). The FastAPI server loads the same store on startup so `GET /api/v1/emg/stats` and `oiw emg status` agree.

### CodeJam corpus ingest (WP-08 PR-6 — Track B)

```bash
# Clone the SAP-samples CodeJam repo
git clone --depth 1 \
  https://github.com/SAP-samples/connecting-systems-services-integration-suite-codejam \
  /tmp/sap-codejam

# Walk every ZIP, extract iFlows, parse with the (fixed) BPMN2 parser,
# redact, persist to packages/seed-corpus/artifacts/codejam-* + EMG store.
python scripts/ingest_codejam.py
```

Retrieval proof at `docs/emg/wp08-codejam-retrieval.yaml`.

### EmbeddingGemma-300m backend (WP-08 PR-2 — Track A-002, optional)

The TF-IDF embedder is the CI default (always available, no dependencies). For real semantic paraphrase detection, install the Gemma extra:

```bash
pip install 'oiw[embeddings]'   # sentence-transformers + torch

# Switch the EMG store to Gemma
export OIW_EMBEDDING_BACKEND=gemma
export OIW_EMBEDDING_MODEL=google/embeddinggemma-300m
export OIW_EMBEDDING_DIM=768
oiw emg reindex
```

**License note:** EmbeddingGemma is under Google's Gemma terms, not Apache-2.0. The model is downloaded at first use by `sentence-transformers`; we do NOT vendor weights. CI must NOT require the download (`OIW_EMBEDDING_BACKEND=tfidf` in GitHub Actions). When `sentence-transformers` is not installed, `GemmaEmbedder` falls back to a deterministic hash-based pseudo-embedding (preserves exact-match similarity, never crashes) — see DEV-026.

## Repository layout

```
open-integration-workbench/
├── DEVELOPMENT_LOG.md              # Single source of truth (read this first)
├── Work Package 8.md               # WP-08 spec — productize the learning loop
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
│   ├── seed-corpus/                # CodeJam + tenant artifacts (WP-08 PR-6/PR-7)
│   │   └── artifacts/codejam-*/     # Redacted IR + import report + metadata
│   └── test-fixtures/              # Golden import/export fixtures
├── deploy/                         # Docker Compose, Helm, WSL bootstrap
├── docs/                           # ADRs, compatibility matrix, security, contributor guide
│   └── emg/                        # WP-08 retrieval proofs + LLM roadblock guides
├── examples/                       # Reference scenarios (order-to-s4, sftp-order-drop)
├── scripts/                        # Fixture generators + tenant_smoke.py + ingest_codejam.py
└── .github/workflows/              # CI: validate-on-pr (10 jobs), security-scan, release
```

See spec §20 for the full target structure.

## Testing

| Package | Tests | Description |
|---------|-------|-------------|
| `apps/cli` | 376 | CLI, validators, patch engine, runtime steps, **agent pipeline + EMG retrieval** (WP-04/05), **deploy + EMG** (WP-05), **durable JsonlEmgStore** (WP-08 PR-1), **Gemma/Fastembed backends + auto-select** (WP-08 PR-2), **callActivity classification by activityType** (WP-08 PR-5), **real SapCiTenantAdapter** (WP-08 Track 0) |
| `apps/server-python-prototype` | 87 | REST API, PATCH endpoints, simulate, resources, diff, agent pipeline, trajectoryId (OW-027), **durable EMG store reads on startup** (WP-08 PR-3) |
| `apps/mcp-server` | 20 | MCP protocol, 12 tools (incl. **flow.create**), baseRevision enforcement (WP-04 Task 6) |
| `packages/seed-corpus` | 132 | Synthesis, redaction, ingestion, promotion, **durable promotion persistence** (WP-08 PR-3/A-004), real CodeJam artifact handling |
| `services/model-gateway-python` | 43 | Redaction, budget, circuit breaker, prompts, API |
| `tests/agent_eval` | 30 | Agent evaluation harness (WP-04 Task 8): benchmarks, runner, metrics, **LLM runner** (OW-023), **structured metrics** (OW-024) |
| `apps/web/e2e` | 2 | Playwright E2E: co-pilot suggest+apply, reject (WP-04 Task 9) |
| **Total** | **615** | 613 unit/integration + 2 E2E; **all green in CI** ✅ (5 pre-existing async-test failures in `apps/cli/tests/agent/` are deselected — they're pytest-asyncio version mismatches, unrelated to WP-08) |

CI runs 12 required checks across 3 workflows: **validate-on-pr** (OIW validate+test+build, schema self-check, CLI pytest, API pytest, MCP pytest, gateway pytest, ruff lint, SPA build, DEVELOPMENT_LOG check), **agent-eval** (WP-04 Task 8 benchmark suite), **e2e** (OW-026 Playwright co-pilot tests). All new WP-08 tests use `httpx.MockTransport` (no network in CI); real-tenant commands (`oiw tenant *`) are manual — `OIW_USE_REAL_TENANT` must NEVER be set in CI per WP-08 §10.

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
