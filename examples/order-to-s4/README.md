# Customer Order Integration

Reference scenario for Open Integration Workbench.

> **Spec ref: §26.3 — First Reference Scenario**
> Inbound JSON order → validation → Groovy normalization → XSLT mapping → mocked HTTP receiver → error subprocess

## Run it

From the repository root (after `pip install -e apps/cli`):

```bash
cd examples/order-to-s4
oiw validate --strict
oiw test --all
oiw build --target sap-cloud-integration-2026-07
oiw git status
```

## Layout

```
order-to-s4/
├── oiw.yaml                              # project manifest (§7.1)
├── package/package.yaml
├── flows/order-to-s4/
│   ├── flow.yaml                         # flow IR (§7.2)
│   ├── diagram.json                      # visual layout only (§7.3 rule 4)
│   ├── resources/
│   │   ├── scripts/normalizeOrder.groovy # Groovy (stub in Python prototype; §9.4)
│   │   ├── mappings/order.xsl            # XSLT 1.0 (Phase 2: Saxon-HE XSLT 2.0)
│   │   └── schemas/order.schema.json
│   └── tests/
│       ├── happy-path.yaml               # FlowTest IR (§7.4)
│       ├── invalid-payload.yaml
│       └── fixtures/order.json
├── environments/
│   ├── dev.yaml
│   └── prod.yaml
└── policies/integration-policy.yaml
```

## What it exercises

- Visual graph modelling (flow.yaml + diagram.json)
- Payload validation (validator.json-schema)
- Groovy (stubbed interpreter; full sandbox deferred to Phase 2)
- XSLT mapping (lxml XSLT 1.0; Saxon-HE 2.0 in Phase 2)
- Receiver mocking (FlowTest mocks block)
- Error subprocess (defaultExceptionSubprocess)
- Local trace (per-node enter/exit/error entries)
- Deterministic build (oiw build → dist/ with sha256 digest)
- AI benchmarking (Phase 3 will use this scenario in the agent evaluation suite, spec §23.1)
