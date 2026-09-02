# 5-Minute Quickstart

> No SAP tenant. No Docker. No credentials. Just you, your terminal, and
> integration flows as code. Everything below runs 100% locally.

## What you'll do

1. Install the `oiw` CLI
2. Create an integration project from a template
3. Write a test, run it, watch the trace
4. Build a deterministic artifact
5. (The party trick) Import one of YOUR existing iFlow ZIPs and see it as readable, diffable code

## 1. Install

Requires Python 3.11+.

```bash
git clone https://github.com/d3vr19/open-integration-workbench.git
cd open-integration-workbench
python -m venv .venv && source .venv/bin/activate
pip install -e apps/cli
```

(On a [uv](https://docs.astral.sh/uv/)-managed venv: `uv pip install -e apps/cli`.)

Verify:

```bash
oiw --version
oiw init --help
```

## 2. Create a project

```bash
oiw init my-first-flow --archetype api-to-erp
cd my-first-flow
oiw validate
```

`api-to-erp` scaffolds a realistic flow: HTTPS sender → content modifier →
XSLT transform → HTTP receiver, with tests and resources included.

## 3. Test it

```bash
oiw test
```

```
PASS  api-to-erp :: smoke  (0 ms)
tests: 1/1 passed, 0 failed
```

The test executed the flow **locally** — every step ran real logic
(JSON↔XML conversion, routing, content modification) with the HTTP
endpoints mocked at the world seam. Your receiver config says
`https://example.invalid/api`? Doesn't matter — that's the boundary where
the simulation world takes over.

Want the JSON output for CI?

```bash
oiw test --json
```

## 4. See the execution trace

The test runner records a full per-step trace. Run with the JSON output
and inspect it:

```bash
oiw test --json | python -m json.tool | head -40
```

Every step's entry/exit, the exchange status, and (for `--engine real`
runs) MPL-shaped records are in there. In the [web workbench](#the-web-workbench-optional)
the same trace renders as a live streaming panel on the flow canvas.

> `oiw test --engine real` additionally REFUSES steps whose local
> implementation is a stub — loud honesty about what "green locally"
> actually covers.

## 5. Build

```bash
oiw build --target sap-cloud-integration-2026-07
```

Deterministic: same project revision + same compiler → byte-identical
artifact (sha256 recorded in `.oiw/compiler.lock`). The build output is a
SAP-compatible designtime ZIP you can inspect with `oiw archive inspect`.

## 6. The party trick: import YOUR iFlow

Take any iFlow ZIP you exported from SAP Cloud Integration and:

```bash
oiw import path/to/your-iflow.zip
```

OIW parses the BPMN2 into its normalized IR and writes **readable,
diffable, Git-friendly** `flow.yaml` files. What SAP gives you as an
opaque bundle becomes:

```yaml
apiVersion: oiw.dev/v1alpha1
kind: IntegrationFlow
metadata:
  id: getDistribucion
  name: getDistribucion
spec:
  entrypoints:
    - id: sender-main
      type: sender.http
      config: { path: /getDistribucion, methods: [GET] }
  nodes:
    - id: step-1
      type: modifier.content     # the Enricher, decoded
      config: { ... }
    - id: step-2
      type: script.groovy
      ...
```

Every recognized component is typed and labeled with its fidelity
(`compatible-subset` = we simulate it locally; `tenant-required` = needs a
tenant). Unrecognized vendor extensions are never silently dropped — they
land in an explicit `unsupported` list you can review.

Now `git init`, commit, and you're doing CPI development the way the rest
of the software world works: **pull requests, diffs, code review**.

## The web workbench (optional)

```bash
pip install -e apps/server-python-prototype
# in a second shell:
cd apps/web && npm install && npm run dev
```

Open http://localhost:5173 — drag-and-drop flow editor, Monaco code
editor for Groovy/XSLT, live simulation trace streaming, semantic diff
viewer.

## Where next

- [README](../README.md) — the full picture
- [Installation guide](installation.md) — Docker/WSL2 setups, the model gateway, tenant connectivity
- `oiw --help` — 30+ commands (validate, test, build, diff, import, archive inspect, parity, emg, agent, deploy…)

> **The autonomous-creation story**: once you connect a real tenant
> (environment profile + credentials), the same machinery can assemble,
> deploy, and verify integration flows from natural-language directives —
> see [DEVELOPMENT_LOG.md](../DEVELOPMENT_LOG.md) for the live proofs.
> But that's chapter two; the local-first loop above is the product.
