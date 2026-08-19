# OIW Compatibility Matrix

> Spec ref: §4.3 (Explicit Fidelity), §8 (Compatibility Compiler), §9.4 (Initial Step Coverage).
> Last updated: 2026-08-19. Reflects 20 step plugins across Phases 0–6 (WP-06 Track B) + WP-08 PR-5 callActivity classification fixes.

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

## Import parser: callActivity classification (WP-08 PR-5 / B-002)

Real SAP CI iFlow artifacts use `<bpmn2:callActivity>` elements (not `<serviceTask>`)
for most processing steps. Before WP-08 PR-5, the parser only classified `serviceTask`
and dropped `callActivity` entries as "unsupported" — meaning the import report
understated what the parser actually understood.

The fix reads each callActivity's `<ifl:property><key>activityType</key><value>...</value>`
block and maps the SAP CI activityType to an OIW step type:

| SAP CI activityType | OIW step type | Fidelity | Notes |
|---------------------|---------------|----------|-------|
| `Enricher` | `modifier.content` | compatible-subset | Content modifier with body/header/property manipulation |
| `Mapping` / `MessageMapping` | `transform.xslt` | simulated | SAP uses `.mmap` resources; OIW treats as XSLT (DEV-003) |
| `Script` | `script.groovy` | compatible-subset | Standard Groovy script (JVM bridge with `SecureASTCustomizer`) |
| `Script` (name contains "SecureStore") | `unsupported` (tenant-required) | tenant-required | Uses SAP `SecureStoreService` API; preserved as unsupported, not skeletonized |
| `XmlToJsonConverter` | `converter.xml-to-json` | compatible-subset | |
| `JsonToXmlConverter` | `converter.json-to-xml` | compatible-subset | |
| `Filter` | `filter` | compatible-subset | |
| `ContentBasedRouter` / `Router` | `router.content-based` | compatible-subset | |
| `GeneralSplitter` / `Splitter` | `splitter.general` | simulated | DEV-003: stores split items as attachments; full iterator semantics is Phase 2 |
| `Gather` / `Join` | `gather` | simulated | Bounded via `maxItems` |
| `Base64Encoder` / `Encoder` | `encoder.base64` | compatible-subset | |
| `Logger` / `Log` | `log.message` | compatible-subset | Sensitive headers redacted per spec §9.2 step 9 |
| `ProcessCallElement` | `subprocess.local` | simulated | Planned (OW-013) |
| `RequestReply` | `request-reply` | simulated | Planned (OW-013) |
| `DBstorage` | `datastore.write` | tenant-required | SAP message log integration — needs tenant |
| Unknown activityType | `unsupported` | unsupported | **Preserved** in `unsupported_call_activities` with raw properties — NEVER silently dropped (WP-08 B-002 acceptance) |

**Real-tenant before/after (WP-08 PR-5 verification):**
The artifact `Get_ExchangeRates_DEV` (downloaded from a live BTP tenant via `oiw tenant pull`)
was imported before and after the parser fix.

- Before: 2 recognized components (`https_sender` + 1 `serviceTask`).
- After: 6 recognized components (`https_sender` + 1 `serviceTask` + 4 `callActivity`: 2× `modifier.content`, 1× `transform.xslt`, 1× `converter.xml-to-json`).

The 4 newly-classified callActivities were previously silently dropped — exactly
the gap WP-08 §2 "Honest Diagnosis" warns about. See `docs/emg/wp08-codejam-retrieval.yaml`
for the corresponding CodeJam regression test.

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
| `subprocess.local` | Simulated | Planned (OW-013). Now classified from `ProcessCallElement` callActivities (WP-08 PR-5). |
| `request-reply` | Simulated | Planned (OW-013). Now classified from `RequestReply` callActivities (WP-08 PR-5). |
| `datastore.write` / `datastore.read` | Simulated (write tenant-required for `DBstorage`) | Planned (OW-013). `DBstorage` callActivities from real SAP exports are marked tenant-required (WP-08 PR-5). |
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

## Tenant adapter (WP-08 Track 0 + C — read-only)

The real `SapCiTenantAdapter` (in `apps/cli/oiw/tenant/sap_ci_adapter.py`) implements
GET-only operations against a live SAP Cloud Integration tenant via HTTP Basic auth:

| Operation | Status | Notes |
|-----------|--------|-------|
| `connect(profile)` | DONE | Validates Basic auth by GET-ing the OData service root. Raises `SapCiTenantError` on HTTP 401. |
| `list_packages(top)` | DONE | `GET /IntegrationPackages?$top=N`. Parses SAP CI's `{"d": {"results": [...]}}` OData format. |
| `list_artifacts(package_id, top)` | DONE | `GET /IntegrationPackages('{id}')/IntegrationDesigntimeArtifacts?$top=N`. |
| `download_artifact(artifact_id, version)` | DONE | `GET /IntegrationDesigntimeArtifacts(Id='{id}',Version='{ver}')/$value`. Returns raw ZIP bytes. |
| `get_artifact_version(package_id)` | DONE | Drift hook: returns the latest artifact's version. |
| `get_artifact_digest(package_id)` | DONE | Drift hook: returns `sha256:<hex>` of the latest artifact ZIP bytes. |
| `upload_package` | NotImplementedError | Per WP-08 §C-004 ("the tenant is a library, not a scratchpad"). Tracked on OW-031 (Track D-004). |
| `deploy` | NotImplementedError | Per WP-08 §C-004. Tracked on OW-031. |
| `poll_deployment` | NotImplementedError | Per WP-08 §C-004. Tracked on OW-031. |
| `get_runtime_logs` | NotImplementedError | Per WP-08 §C-004. |

`build_tenant_adapter(use_real=None)` factory returns the real adapter when
`OIW_USE_REAL_TENANT=1`, else the existing `MockSapCiTenantAdapter`. CI stays
on the mock per WP-08 §10 ("Default `OIW_USE_REAL_TENANT=1` in CI" is forbidden).

**Verified end-to-end against a live BTP tenant (2026-08-19):**
50 packages listed, 91 artifacts in 1 package, 1 artifact downloaded (8861 bytes).

## Target profiles

| Profile | Status | Notes |
|---------|--------|-------|
| `sap-cloud-integration-2026-07` | PARTIAL | Reference scenario round-trips with documented deviations (see `packages/test-fixtures/`). WP-08 PR-5 callActivity classification improved real-artifact import from 2 → 6 recognized components. |

## Known deviations

See `DEVELOPMENT_LOG.md` → Deviation Registry.

