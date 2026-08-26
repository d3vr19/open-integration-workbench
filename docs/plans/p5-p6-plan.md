# P5 + P6 Plan: The Simulated World → Hands-Free Proof

> Governing addendum to hands-free-roadmap.md. Status: ACTIVE (2026-08-26).
> Every PR states its milestone ID (P5a-M1 … P6-M3). Deviations recorded here first.

## 0. The load-bearing insight

The live tenant taught us the thing this whole phase hangs on:

**"Green locally" is only worth something if it predicts "STARTED remotely."**

Our generated iFlow passed SAP's *model* validation (upload 200, deploy 202)
but failed *runtime start* (Status=ERROR, zero MPL entries). That failure mode
is exactly what a shallow simulator cannot catch. Therefore P5 is not "build a
simulator" in the abstract — it is:

> Build a local execution world whose verdicts are **calibrated against the
> tenant oracle**, with parity measured continuously and honestly labeled.

We own a real oracle now: upload→deploy→poll in seconds. P5 exploits it.

## 1. Tenant-API needs (operator-provided specs)

| Spec | Priority | Used for |
|---|---|---|
| **MPL (MessageProcessingLogs)** | NOW | Exact schema (LogStart/LogEnd/Status/CustomStatus/ErrorInformation + children) so local traces are structurally identical; post-deploy comparison |
| **Log Files / MPL attachments** | NOW | Deployment/runtime error details (our current ERROR produces no MPL rows — need to know where SAP puts startup-failure diagnostics) |
| Message Stores / DataStore | when 5c starts | Simulating `datastore.write` semantics locally (currently tenant-required) |
| Security Content (keystores/credentials) | deferred | Only once generated flows reference credential artifacts |

## 2. Milestones

### P5a — Message-execution engine ("the body")

- **M1 · Oracle harness** *(first — also unblocks the current ERROR)*
  `oiw tenant calibrate --package X --artifact Y [--message-file f]`:
  upload → deploy → poll → if STARTED, POST a test message to the flow's
  HTTPS endpoint → pull MPL rows → write a calibration report YAML
  (local expectation vs tenant reality). Runs against scratch packages only;
  reuses allowlist/pinning policy. Output feeds the parity suite (M3) and
  gives us the missing runtime-error diagnostics.
- **M2 · Real payload execution** in `oiw test`
  New engine flag (`--engine real`, default stays simulated): Exchange
  objects carry actual bytes/headers; steps execute true logic — Groovy via
  the JVM sandbox bridge (exists), JSON↔XML via lxml, router conditions via
  the same expression forms CPI uses (from fixture evidence:
  `${property.x} in ${property.y}`, xpath). Emits **MPL-shaped trace
  records** (same field names/status vocabulary as the real API).
- **M3 · Parity suite** ← the honesty instrument
  Golden corpus starting at 10 flows (held-out async + CodeJam-derived +
  synthetic variants). Each flow runs locally AND through M1's oracle;
  parity = agreement on {deployable?, started?, per-step transforms,
  final body}. Fidelity metric published in `docs/emg/sim-parity.yaml`.
  **Gate: ≥90% agreement on the supported node subset before P5b.**
  Every parity failure becomes either an exporter fix or a new executor
  test case — the corpus grows only from observed mismatches.

### P5b — World dynamics ("the environment")

- Mock receiver server (HTTP) + fake SFTP drop, configurable per
  EnvironmentProfile; fault injection matrix (timeout/5xx/malformed/schema-drift).
- Deterministic seeds so tests reproduce.

### P5c — Reward function v1 ("the hunger")

- Map execution telemetry onto the existing 9-dim reward vector
  (emg/reward.py): deployable, started, test-passed, steps-clean,
  latency-bounded, etc. Local reward == what the oracle would say, modulo
  measured parity error.
- Failed runs auto-capture learning sessions → EMG (existing pipeline),
  tagged provenance=simulated-world vs tenant.

### P5d — Turbo loop ("the muscles")

- `oiw agent --turbo`: plan→implement→simulate→repair cycles, no per-step
  approvals; bounded by token/wall-clock/iteration caps; tenant adapter
  unreachable from turbo mode (code-level guard, not convention);
  every trajectory recorded.
- Human gate remains PROPOSED→APPROVED before any tenant touch (P6 uses it).

### P6 — Hands-free proof

- **M1**: single command demo: `REQUIREMENT.md` → turbo artifact green in sim
  → drift check → one human approval → upload+deploy → STARTED → verify.
- **M2**: transcript + timings captured to docs/plans/p6-demo.yaml; roadmap updated.
- **M3**: README status flip.

## 3. Sequencing

```
NOW ──► P5a-M1 (oracle; also diagnoses current ERROR)
     ──► P4-close (runtime-start fidelity iterations using M1)
     ──► P5a-M2 ──► P5a-M3 ──gate──► P5b ──► P5c ──► P5d ──► P6
```

P4's remaining work (runtime-START on generated bundles) and P5a-M1 are the
same loop from two sides; do them together.

## 4. Risks

| Risk | Mitigation |
|---|---|
| Runtime-start failures opaque (no MPL) | M1 hunts Log Files/attachments location; worst case bisect bundle contents against a known-good fixture |
| Parity suite scope creep | Node subset frozen per milestone; unsupported types raise loudly (exporter precedent) |
| Oracle cost on tenant | Scratch package only; calibrate on demand, cache reports; never CI |
| Turbo autonomy risk | Hard-coded adapter guard + budgets; trajectories always recorded |

## 5. Progress log (append-only)

- 2026-08-26 — Plan ratified; awaiting operator specs for MPL + Log Files.
## 6. P5a-M1 execution log (append-only)

- 2026-08-26 — M1 SHIPPED: `oiw tenant calibrate` (apps/cli/oiw/tenant/calibrate.py)
  runs export→upload→deploy→poll→[message]→MPL and writes a calibration YAML.
  Live-run verified against AdaequareGST/open_mateo_test.
- API ground truth captured this session:
  - LogFiles endpoint = HTTP 501 on CF tenants (server logs unavailable).
  - RuntimeArtifactErrorInformations exists in edmx (HasStream) but the
    tenant does NOT serve it ("could not find entity set").
  - MPL nav ErrorInformation exists; startup failures produce NO MPL rows,
    so error detail must come from bundle bisection.
  - $expand unsupported on IntegrationRuntimeArtifacts queries.
- Bisection results so far (all upload→deploy→poll via oracle):
  - Drop Enricher (sender→receiver only): still ERROR ⇒ not the cause.
  - Import-Package/Import-Service headers: naive fold ⇒ upload 400
    ("invalid header field line 11"); folded impl added to exporter;
    VERBATIM SAP-authored fixture manifest (identity swapped): still ERROR
    ⇒ OSGi headers EXONERATED. Fault is in the .iflw itself.
- Queued hypotheses (next session, cheapest first):
  H1: BPMN element-id prefixes matter to CPI's runtime compiler
      (fixture uses StartEvent_/CallActivity_/ServiceTask_/ExclusiveGateway_;
       we emit generic Step_N). Fix = prefix-correct ids.
  H2: Enricher with EMPTY propertyTable + constant body NPEs runtime init
      (fixture rows are always populated). Fix = emit a real row or drop
      wrapContent path.
  H3: metainfo.prop carried required config we can't see (original lost);
      probe by exporting a UI-created trivial iFlow's bytes as reference.
- 2026-08-26 (cont.) — BISECTION MATRIX (all via calibrate loop, live):
  | Variant | Result |
  |---|---|
  | Bare Start→End (scaffold only) | **STARTED ✅** |
  | + Enricher (log.message→Content-Modifier shape) | **STARTED ✅** |
  | + Receiver (ExternalCall serviceTask + messageFlow) | ERROR |
  Eliminated as causes: Enricher encoding; OSGi manifest headers; dashed
  node ids; process-scoped vs collaboration-scoped messageFlow placement
  (moved to collab per fixture; still ERROR); receiver URL DNS validity.
  Property-level diff of our receiver MF vs fixture MessageFlow_80:
  NO missing keys; only semantic value diffs (proxyType internet≠sapcc,
  httpAddressQuery empty) — unlikely culprits.
  ⇒ The receiver path needs a REFERENCE EXPORT: create a trivial iFlow
    WITH an HTTP receiver in the tenant UI, download its bundle bytes
    (tenant pull), and byte-diff the .iflw against ours. That will point
    at whatever attribute/element CPI's runtime compiler demands that we
    cannot guess from the CodeJam fixture (whose receivers all live in
    subprocesses — possible structural requirement).
  NOTE: operator can also just deploy once via UI and share the downloaded
  artifact zip — no devtools needed for THIS step.
- 2026-08-26 (cont. 2) — REFERENCE-EXPORT ANALYSIS (operator provided
  iflows/testing_oiw*.zip — a UI-authored flow with an HTTP receiver):
  - STRUCTURAL REVELATION: in modern CPI exports the receiver is wired as
    **EndEvent(messageEventDefinition) + messageFlow(EndEvent→Participant)**
    — there is NO main-process serviceTask/ExternalCall (that shape only
    occurs inside local subprocesses). Exporter v3 rewritten accordingly:
    terminal receivers collapse into EndEvent_1; full 48-key receiver
    property set mirrored from the reference; suite green.
  - Reference config facts: proxyType=`default` (not internet),
    URL externalized as {{openMateoURL}} via parameters.prop/.propdef,
    authenticationMethod=Client Certificate with empty credentialName.
  - Live results: ref-verbatim content on open_mateo_test ⇒ new distinct
    status FAILED (likely empty externalized URL + missing credential).
    `testing_oiw` itself was NEVER deployed by the operator (no runtime row)
    so it is not evidence of a working shape.
  - Tenant RESTORED to known-good: bare pass-through re-deployed,
    final status **STARTED** ✅ — open_mateo_test is healthy again.
- NEXT (ranked): H-A retry EndEvent-model receiver with proxyType=default +
  literal reachable URL + no ext-param indirection; H-B replicate reference's
  FULL collaboration prop set (cors*/accessControl keys); H-C create the
  reference flow fresh in UI, DEPLOY it once via UI, then tenant-pull BOTH
  designtime+runtime state for a proven-good byte baseline.
- 2026-08-26 (final) — ENVIRONMENTAL FINDING + session close:
  - Configurations API confirmed artifact-scoped only
    (/IntegrationDesigntimeArtifacts(Id,V)/Configurations); testing_oiw's
    openMateoURL is EMPTY on the tenant ⇒ its FAILED was config, not structure.
  - proxyType=default, IntegrationProcess participant(processRef) both tested:
    NOT the cause.
  - Operator's own UI-authored receiver flow (URL+auth fixed by us) ALSO fails
    runtime-start ⇒ receiver failures are NOT exporter-specific.
  - Tenant currently shows ~600 STARTED flows incl. receivers ⇒ receivers CAN
    run here; but by session end EVEN previously-STARTED bare content redeployed
    by us went ERROR ⇒ strong evidence of deploy-rate/runtime-wedge behavior
    after ~15 rapid redeploys in one hour. Oracle verdicts are point-in-time;
    add cool-down/backoff to calibrate polling next session.
  - open_mateo_test left holding last-attempt content; next session FIRST
    re-run calibrate after cool-down (bare variant expected STARTED again),
    THEN resume receiver work with fresh runtime state.
  - Transplant lesson: $value downloads of OTHER artifacts use the
    content-export archive format (resources.cnt…), not project zips —
    handle both formats when transplanting/diffing (new TODO in exporter).
- 2026-08-26 (session 3) — WEDGE CONFIRMED + RECEIVER MATRIX CLOSED:
  - Cool-down verdict: bare re-calibrate → **STARTED ✅** minutes into the
    session. Yesterday's deploy-rate/runtime-wedge theory confirmed; oracle
    verdicts taken today are clean.
  - H-A REFUTED: v3 EndEvent-model receiver with literal reachable URL +
    proxyType=default + authenticationMethod=None → ERROR on healthy tenant.
  - Byte-parity matrix vs operator-provided UI-authored reference
    (testing_oiw zip; structural diff tooling in session log):
    | Variant | Delta vs H-A | Verdict |
    |---|---|---|
    | full | collab 15-key set (cors*/accessControl/log, returnExceptionToSender=false, cmdVariantUri 1.2.4) + sender MF 1.5.3/xsrf=1/clientCertificates + receiver value alignment | ERROR |
    | di | reference bpmndi DI section (8 shapes/edges, ids adapted) | ERROR |
    | fulldi | all of the above combined | ERROR |
  - Reference facts newly extracted: UI exports carry a FULL bpmndi
    diagram section (bare tolerates absence; receivers unproven either way
    — tested, not sufficient); sender HTTPS adapter now at version 1.5.3
    with a clientCertificates property row; collaboration default set has
    15 keys (we emitted 7); `testing_oiw` does NOT exist on this tenant as
    designtime or runtime ⇒ there is still NO proven-good receiver
    baseline anywhere.
  - CONCLUSION: every replicable content difference is eliminated.
    Bare starts via our API path seconds before/after receiver variants
    fail ⇒ failure is NOT bundle bytes. Remaining hypotheses:
    (i) deploy-path semantics — PUT-update + DeployIntegrationDesigntimeArtifact
    may skip regeneration the UI deploy performs for messageFlow-bearing
    flows (~600 STARTED receivers were all UI-deployed);
    (ii) tenant security/landscape material validated only on some paths.
  - DECISIVE NEXT TEST (operator, ~2 min): create a trivial iFlow WITH an
    HTTP receiver in the tenant UI and deploy it ONCE via the UI. If it
    fails → environmental, stop artifact work, raise with SAP. If it
    starts → we pull its bytes, PUT them onto open_mateo_test via API and
    deploy: API-round ERROR ⇒ deploy-path wedge proven; START ⇒ byte-diff
    isolates the final delta.
  - Side findings: runtime message endpoint /http/<path> returns 403 with
    basic auth + xsrfProtection=0 (entrypoint exercise needs its own fix —
    ref uses xsrfProtection=1); adapter CSRF token does not survive rapid
    reconnects — space calibrate runs ≥60s or refetch per connect;
    open_mateo_test restored to bare/STARTED at session close.
- 2026-08-26 (session 4) — RECEIVER BLOCKER SOLVED: **our bundles START**.
  Operator deployed testing_oiw via UI (sender path /oiw, GET, ext-query)
  ⇒ STARTED, and supplied a fresh export. Then:
  - Transplant v1 (UI bytes onto open_mateo_test via API) ERROR — confound:
    /oiw endpoint collision with running testing_oiw.
  - Transplant v2 (same bytes, unique /oiw-hc1) → **STARTED** ⇒ API
    PUT-update + DeployIntegrationDesigntimeArtifact path fully capable of
    starting EndEvent-model receivers. Deploy-path-wedge theory dead.
  - Single-variable regression ladder from green (one deploy per factor):
    | Factor (ours vs reference) | Verdict |
    |---|---|
    | authenticationMethod None (vs Client Certificate) | STARTED — exonerated |
    | literal URL folded INTO httpAddressWithoutQuery | **ERROR — FATAL #1** |
    | split form: address→WithoutQuery, query→httpAddressQuery (both literal) | STARTED |
    | locationID MBP / system <id> / allowedHeaders / MPLAttachments / timeout | STARTED — exonerated |
    | retry trio (idleTimeout '' / interval '10000' / iteration '3') | **ERROR** |
    | retryInterval '10000' ALONE | **ERROR — FATAL #2** |
  - Production corroboration: every STARTED HTTP receiver on the tenant
    (Hiring_Darwin_to_SFEC etc.) carries idleTimeout=300000,
    retryInterval=5, retryIteration=1. Our '10000' was fixture-inherited
    (CodeJam receivers never ran).
  - Exporter v4 fixes (apps/cli/oiw/compiler/sap_export.py):
    1. urlsplit receiver config.url → httpAddressWithoutQuery gets
       scheme://host/path, httpAddressQuery gets the query string.
    2. Retry values aligned to proven set (300000 / 5 / 1).
  - FINAL ORACLE VERDICT: exporter v4 bundle on open_mateo_test via plain
    `oiw tenant calibrate` → **STARTED ✅✅** — collab prop count, DI
    section, sender versions/xsrf, auth method, and externalization all
    EXONERATED by construction (exporter output lacks them and starts).
  - OPEN (next): message exercise returns HTTP 403 at /http/<path> +
    zero MPL rows — runtime-endpoint auth (xsrfProtection?) is the next
    seam before reward-function wiring can consume live executions.
  - SESSION 4 CLOSE — message ingress SOLVED (operator tip): /http/<path>
    lives on the RUNTIME host (landscape segment takes '-rt' suffix);
    designtime host 403s. `runtime_base_url()` derives it (+env override
    OIW_TENANT_RUNTIME_URL); send verb now honors entrypoint methods.
    FULL ORACLE LOOP GREEN: upload → STARTED → GET /http/open_mateo_test
    → HTTP **200** → MPL row Status=**COMPLETED**
    (AGqOeXB4VGtDoi1r--B4S_3QMcKz). P5a execution engine has live
    ground truth end-to-end; reward wiring (P5c) can consume MPL verdicts.
