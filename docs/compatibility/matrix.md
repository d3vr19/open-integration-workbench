# OIW Compatibility Matrix

> Spec ref: §4.3 (Explicit Fidelity), §8 (Compatibility Compiler), §9.4 (Initial Step Coverage).
> Last updated: 2026-08-04. Reflects 20 step plugins across Phases 0–6 (WP-06 Track B).

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
| `sender.soap` | Simulated | **WP-06 B-001**: Parses SOAP envelope, extracts operation from Body. Mock response injection. |
| `sender.timer` | Simulated | Cron expression; fires immediately in test. Planned. |
| `sender.jms` | Unsupported | Preserved as opaque metadata. Planned for Phase 6. |
| `sender.sftp` | Unsupported | Planned for Phase 6. |

## Process steps

| Step | Fidelity | Notes |
|------|----------|-------|
| `modifier.content` | Compatible-subset | Headers, properties, body. Supports `${header.X}`, `${property.Y}`, `${body}` interpolation. |
| `validator.json-schema` | Compatible-subset | Draft-07 JSON Schema. |
| `script.groovy` | Compatible-subset (sandboxed) | **JVM Bridge (P1a)**: Groovy scripts execute via sandboxed JVM subprocess with `SecureASTCustomizer`. Disallowed imports: `Runtime`, `ProcessBuilder`, `System`, `Thread`, `java.net.*`, `java.io.File*`, `GroovyShell`, `reflect.*`. Falls back to stub interpreter (DEV-003) if JVM bridge not available. SAP-specific APIs (`ITApiFactory`, `SecureStoreService`) are not supported — tenant-required. |
| `transform.xslt` | Simulated | **DEV-003**: Python prototype uses XSLT 1.0 (lxml). XSLT 2.0/3.0 features (`xsl:for-each-group`, `xsl:function`, `xsl:analyze-string`, `xsl:perform-sort`, sequence types) are **unsupported**. Saxon-HE XSLT 2.0 subset via subprocess is Phase 2 (OW-003). Downgraded from "compatible-subset" to "simulated" per spec §4.3. **Note**: XSLT 1.0 transforms execute correctly via lxml — the "simulated" label reflects the inability to execute XSLT 2.0/3.0 features, not inaccuracy in 1.0 execution. A consultant with 1.0-only mappings will see correct results; mappings using 2.0 features will fail. |
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
| `receiver.soap` | Simulated | **WP-06 B-001**: Generates SOAP response envelope, SOAPAction header. Mock injection. |
| `receiver.odata-v4` | Simulated | **WP-06 B-002**: OData V4 GET/POST/PUT/PATCH/DELETE, pagination (@odata.nextLink), $filter/$select. maxPages enforcement. OIW-W001 on missing timeout. |
| `receiver.idoc` | Simulated | **WP-06 B-003**: IDoc XML segment parsing, known type validation (ORDERS05, MATMAS05, etc.), OIW-W002 on unknown type, acknowledgment generation. |
| `receiver.mail` | Simulated | **WP-06 B-004**: SMTP email sending, HTML/plain text, mock injection, SMTP status codes. |
| `receiver.jdbc` | Unsupported | Planned for Phase 6. |

## Target profiles

| Profile | Status | Notes |
|---------|--------|-------|
| `sap-cloud-integration-2026-07` | PARTIAL | Reference scenario round-trips with documented deviations (see `packages/test-fixtures/`). |

## Known deviations

See `DEVELOPMENT_LOG.md` → Deviation Registry.
