# SFTP Order Drop

Reference scenario for Open Integration Workbench exercising the Phase 1
MVP step coverage (spec §9.4): splitter, filter, gather, encoder.base64,
and receiver.sftp.

> **Spec ref: §9.4 (Initial Step Coverage), §26.3 (reference scenario pattern).**

## Scenario

Inbound JSON batch of orders → JSON Schema validation → splitter (bounded) →
filter → gather (bounded) → base64 encode → mocked SFTP receiver.

## Run it

From the repository root (after `pip install -e apps/cli`):

```bash
cd examples/sftp-order-drop
oiw validate --strict
oiw test --all
oiw build --target sap-cloud-integration-2026-07
oiw git status
```

## Layout

```
sftp-order-drop/
├── oiw.yaml                              # project manifest (§7.1)
├── package/package.yaml
├── flows/batch-orders/
│   ├── flow.yaml                         # flow IR (§7.2)
│   ├── diagram.json                      # visual layout only (§7.3 rule 4)
│   ├── resources/
│   │   └── schemas/batch.schema.json
│   └── tests/
│       ├── happy-path.yaml               # FlowTest IR (§7.4)
│       ├── invalid-payload.yaml
│       └── fixtures/batch.json
├── environments/
│   ├── dev.yaml
│   └── prod.yaml
└── policies/integration-policy.yaml
```

## What it exercises

- Visual graph modelling (flow.yaml + diagram.json)
- Payload validation (validator.json-schema)
- Bounded splitter (splitter.general with maxItems=100)
- Filter (filter with `true` expression — in Phase 2 this would inspect each split item)
- Bounded gather (gather with maxItems=100)
- Base64 encoding (encoder.base64)
- SFTP receiver mocking (receiver.sftp + FlowTest mocks block)
- Error subprocess (defaultExceptionSubprocess)
- Local trace (per-node enter/exit/error entries)
- Deterministic build (oiw build → dist/ with sha256 digest)
