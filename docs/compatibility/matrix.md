# OIW Compatibility Matrix

> Spec ref: §4.3 (Explicit Fidelity), §8 (Compatibility Compiler), §9.4 (Initial Step Coverage).
> Last updated: 2026-08-01. Reflects 15 step plugins across Phases 0–3.

This matrix records the **current** fidelity level of each supported component.
Every entry MUST link to a fixture (spec §8.5) and a test that proves the claim.

## Legend

| Fidelity | Meaning |
|----------|---------|
| Authoring only | Can be modelled and exported, but not executed locally |
| Simulated | Behaviour is approximated for development tests |
| Compatible subset | Behaviour is expected to match documented semantics for supported options |
| Tenant required | Must run against a real SAP tenant |
| Unsupported | Preserved as opaque metadata where possible |

## Senders (entrypoints)

| Step | Fidelity | Notes |
|------|----------|-------|
| `sender.http` | Simulated | Test harness provides the request body and headers (spec §9.4). |
| `sender.timer` | Simulated | Cron expression; fires immediately in test. Planned. |
| `sender.jms` | Unsupported | Preserved as opaque metadata. Planned for Phase 6. |
| `sender.sftp` | Unsupported | Planned for Phase 6. |

## Process steps

| Step | Fidelity | Notes |
|------|----------|-------|
| `modifier.content` | Compatible-subset | Headers, properties, body. Supports `${header.X}`, `${property.Y}`, `${body}` interpolation. |
| `validator.json-schema` | Compatible-subset | Draft-07 JSON Schema. |
| `script.groovy` | Simulated | **DEV-003**: stub interpreter supports `message.setHeader/setProperty/setBody` only. Full Groovy execution deferred to Phase 2 (services/runtime-worker with seccomp isolation). |
| `transform.xslt` | Compatible-subset | **DEV-003**: Python prototype uses XSLT 1.0 (lxml). XSLT 2.0 subset via Saxon-HE is Phase 2. |
| `converter.json-to-xml` | Compatible-subset | Simple JSON→XML with configurable root element. |
| `converter.xml-to-json` | Compatible-subset | Simple XML→JSON; optional `rootElement` wrapper. |
| `router.content-based` | Compatible-subset | Simple `${property.X} == 'value'` and `true`/`false` expressions. |
| `filter` | Compatible-subset | Drops message if expression evaluates false; supports same expression language as router. |
| `encoder.base64` | Compatible-subset | Encode + decode. |
| `splitter.general` | Simulated | **DEV-003**: prototype stores split items as attachments; full iterator semantics (per-item sub-flow execution) is Phase 2. Bounded via `maxItems`/`maxIterations` (OIW-E003 enforces). |
| `gather` | Simulated | Bounded via `maxItems`. Supports `concat` and `merge` strategies for JSON; concat for XML. |
| `subprocess.exception` | Compatible-subset | Implemented via `errorHandling.defaultExceptionSubprocess`. |
| `subprocess.local` | Simulated | Planned (OW-013). |
| `request-reply` | Simulated | Planned (OW-013). |
| `datastore.write` / `datastore.read` | Simulated | Planned (OW-013). |
| `log.message` | Compatible-subset | Structured log entry; sensitive headers redacted per spec §9.2 step 9. |

## Receivers

| Step | Fidelity | Notes |
|------|----------|-------|
| `receiver.http` | Simulated | Mocked via FlowTest `mocks` block. WireMock backing in Phase 2. |
| `receiver.sftp` | Simulated | Mocked via FlowTest `mocks` block. Records outbound SFTP "call" (sftp:// URL + body) for assertions. Real SFTP support is Phase 6. |
| `receiver.odata-v4` | Unsupported | Planned for Phase 6 (OW-014 depends on this). |
| `receiver.jdbc` | Unsupported | Planned for Phase 6. |

## Target profiles

| Profile | Status | Notes |
|---------|--------|-------|
| `sap-cloud-integration-2026-07` | PARTIAL | Reference scenario round-trips with documented deviations (see `packages/test-fixtures/`). |

## Known deviations

See `DEVELOPMENT_LOG.md` → Deviation Registry.
