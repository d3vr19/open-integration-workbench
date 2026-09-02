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

2026-09-02 — **P6 M1+M2 COMPLETE (live)**: natural-language directive →
turbo-assembled pair (oiw_turbo_fwd + companion PD listener) → both
STARTED on the tenant → message 200 → MPL COMPLETED on BOTH → listener
captured the body. Transcript: docs/plans/p6-demo.yaml. The human role:
the directive + the credentials (env-only). M3 (README flip) pending.
Five new live laws + one honest teacher-summons (converter piece is
live-unproven at message time — pulled from the piece library pending
oracle validation).

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
- 2026-08-26 — GOVERNANCE REPAIR (retroactive deviation record, rule at §0
  header): P5b-M1 and P5c-M1 shipped in session 6 BEFORE P5a-M2/M3 and while
  the §3 parity gate (≥90%) had never been measured — `docs/emg/sim-parity.yaml`
  did not exist. Consequence: reward wiring consumes oracle verdicts with no
  quantified local-fidelity floor underneath. Remedy (same day): backfill
  M2+M3 first; no Phase B/C/D work before the fidelity number is published.
- 2026-08-26 — PHASE A–D PLAN RATIFIED (vision: self-improving human-assisting
  harness for SAP CPI with low-latency simulated artifact building that
  removes the BTP web-UI round-trip tax):
  - **A · Calibration floor** — backfill P5a-M2 (`--engine real`, true-logic
    execution, loud refusal of stub-fidelity steps, MPL-shaped local records)
    + P5a-M3 (parity corpus runner publishing sim-parity.yaml; ≥90% gate,
    min 10 comparable cases; cached oracle reports only, never CI; stale-
    oracle handling per blood law: verdicts are point-in-time).
  - **B · Breadth inside the measured harness** — grammar backlog strictly
    by harvest frequency: Mapping(×191) → XmlToJson(×83) → Filter(×63) →
    Splitter(×17) → ProcessCall(×7); every shape lands through the standing
    METHOD chain PLUS one new step: parity case appended, sim-parity.yaml
    re-published.
  - **C · Closed LLM-free learning loop** — record_oracle_outcome promotion
    hookup on PROJECT_APPROVED; failure→corpus automation (every parity miss
    or oracle ERROR auto-files an exporter-fix candidate or executor test);
    pattern-book crawler on a schedule (harvest stops being one-shot).
  - **D · Turbo as PIECE-ASSEMBLER** — plan→implement→simulate→repair using
    ONLY grammar pieces + corpus; budgets + code-level tenant guard; teacher-
    escalation protocol: when no piece matches or N repair cycles fail, emit
    a structured teacher-request; the answer must merge back as a new piece +
    regression case. TEACHER-SUMMONS RATE is the headline self-improvement
    metric and must trend to zero. LLM is the last-resort teacher, never the
    first mover (operator decision, 2026-08-26).
  Sequencing law: **calibration before coverage before autonomy.**
  - 2026-09-01 — PHASE C SHIPPED (commit pending): learn/loop.py +
    learn/harvest_schedule.py + CLI wiring.
    * C-1 promote_oracle_outcome: full-success oracle runs (STARTED +
      message + all-MPL-COMPLETED) promote a PROJECT_APPROVED insight +
      task node into the durable store, provenance source=tenant-oracle,
      successful_workflow = the flow's actual node chain. Verified
      restart-surviving + retrievable (0.70 confidence on the held-out
      shape). Partial failures never promote.
    * C-2 file_oracle_failure / file_parity_miss: oracle ERROR/TIMEOUT and
      parity `mismatched` verdicts auto-file triage candidates under
      packages/parity-corpus/candidates/ with suggestedTriage
      (exporter-fix | executor-test | triage-required) + the blood-law
      point-in-time caveat. Wired into `oiw tenant calibrate` and
      `oiw parity`. Nothing auto-promotes — triage is a separate step.
    * C-3 harvest_schedule: `oiw emg harvest --if-due [--ttl-days N]` —
      TTL gate (default 7d) + census.yaml back-compat + sidecar
      harvest-state.yaml; scheduled crawlers become no-ops when fresh.
  - 2026-09-01 — PHASE D SHIPPED: agent/turbo.py + agent/turbo_pieces.py +
    CLI (`oiw agent --turbo [--max-iterations N --wall-clock S]`,
    `oiw turbo-stats`).
    * D-2 piece library = real-engine-proven node types only (fidelity !=
      simulated; endpoints = mock seam). transform.xslt / splitter /
      gather are NOT pieces (simulated stubs) — requirements naming them
      teacher-escalate honestly instead of silently dropping.
    * D-1 budgets: iteration cap + wall-clock cap, both enforced.
      Tenant guard is CODE-LEVEL: TurboToolGuard refuses tenant.*/deploy.*
      and LLM tools before any dispatch; the native turbo dispatcher
      touches only the local project tree + local test engine.
    * D-3 teacher requests: structured YAML under .oiw/teacher-requests/
      (kind: no-piece-matches | repair-exhausted | budget-exceeded,
      unmatchedComponents, diagnostics). `oiw turbo-stats` publishes the
      teacher-summons rate (summons/turbo-trajectories) — the headline
      self-improvement metric, must trend to zero.
    * Verified end-to-end: create-flow requirement → COMPLETED iteration 1
      with green smoke test + recorded trajectory; XSLT requirement →
      TEACHER-REQUESTED no-piece-matches (transform.xslt); C-1-seeded EMG
      store → turbo mechanics-first hit (EMG used=True, expert chain
      injected verbatim).
    * Turbo trajectories land in <project>/.oiw/trajectories/ (same
      recorder as the co-pilot path) — no silent runs.
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
    (AGqOeXB4VGtDoi1r--B4S_3QMcKz).     P5a execution engine has live
    ground truth end-to-end; reward wiring (P5c) can consume MPL verdicts.
- 2026-08-26 (session 5) — EXPORTER v6: Request-Reply + ProcessDirect +
  Variables; MULTI-ARTIFACT CHOREOGRAPHY LIVE:
  - Operator reference exports (testing_oiw v3 zip + oiw_pd zip) supplied
    the missing shapes; all mirrored verbatim, no guessing:
    * Request-Reply = serviceTask(activityType=ExternalCall,
      cmdVariantUri ExternalCall/1.0.4) whose HTTP messageFlow attaches
      to the SERVICE TASK (not an EndEvent); response continues downstream.
    * ProcessDirect receiver = EndEvent + messageFlow(name="ProcessDirect",
      address=/oiw_pd, Vendor=SAP, direction=Receiver, 16 props).
    * Variables step = callActivity(activityType=Variables) with
      variable=<row> cells [name,'',type,value,scope] + visibility/
      encrypt/expire props (operator's Write Variables).
  - Mid-flow receiver.http no longer raises — it renders Request-Reply;
    only terminal receivers keep the EndEvent shape.
  - Adapter: allowlist now supports MULTIPLE pinned artifacts per package;
    `calibrate --artifact` selects explicitly (still allowlist-gated);
    deploy/upload re-resolution honors the selection.
  - END-TO-END PROOF (live tenant): GET /http/oiw_pd_hf → HTTP **200**
    with live open-meteo JSON; MPL pairs COMPLETED on open_mateo_test AND
    operator's oiw_pd ~664ms apart ⇒ HTTPS → Request-Reply(open-meteo) →
    Groovy → ProcessDirect(/oiw_pd) → Write Variables executed across two
    artifacts built entirely by the OIW compiler and deployed by pure API.
  - LESSON (second offense): ENDPOINT COLLISIONS. Deploying a second flow
    claiming /oiw_pd_hf while open_mateo_test's chain already bound it
    ⇒ runtime ERROR that looks like a content failure. Rule recorded:
    entrypoint paths are TENANT-GLOBAL; the compiler/oracle must treat
    404-vs-collision distinctly and check bound paths before deploy.
- 2026-08-26 (session 5, cont.) — TOPOLOGY CORRECTED per operator:
  open_mateo_test REIMPLEMENTS testing_oiw v3 (HTTPS /open_mateo_test ->
  RR open-meteo -> Groovy -> ProcessDirect /oiw_pd_hf); oiw_pd_hf is the
  LISTENER (sender.processdirect + variables.write oiw_var=${body}).
  New exporter capability: sender.processdirect entrypoints (16-prop
  sender shape mirrored from oiw_pd reference); calibrate skips HTTP
  message-send for non-HTTP entrypoints. LIVE VERDICT: both STARTED;
  GET trigger -> 200 weather JSON; MPL COMPLETED pairs on BOTH artifacts.
  Designer-open confirmed by operator after v6.1 DI generation.
- 2026-08-26 (SESSION CLOSE / HANDOFF) — READ THIS FIRST, NEXT SELF:
  STATE: PR #4 green at 06d500c; 454 CLI tests pass. Tenant healthy:
    open_mateo_test = writer flow (drops OIW-E2E files via SFTP) STARTED;
    oiw_pd_hf = SFTP poller -> PD(/oiw_pd) forwarder STARTED;
    oiw_pd = operator listener (variables.write oiw_var=${body}).
    Flagship weather chain NOT currently deployed (its PD target /oiw_pd_hf
    listener was replaced by the poller; flagship PD repointed to /oiw_pd
    in /tmp/opencode/final-mateo project — rebuild when needed).
  OPEN THREADS (ranked):
    1. SFTP poll cadence: mirrored cron deploys+STARTs but no pickup
       observed within minutes of a dropped OIW-E2E file. Suspects:
       TIME_INTERVAL schedule semantics slower than they read, or silent
       poll-connect failure (no MPL rows on failed polls). Probe via
       Connectivity Test API (SSH) BEFORE touching code.
    2. Writer-vs-flagship placement on open_mateo_test (operator call;
       recommendation: keep writer, rebuild flagship pair when needed).
    3. Grammar backlog: pattern-book census has 50 nominated shapes;
       Mapping(x191), XmlToJson(x83), Filter(x63), Splitter(x17),
       ProcessCall(x7) top the activity gaps.
    4. Phase 3 turbo loop (THICK) approved and unstarted. Stage 1 of
       LLM-free path agreed: offline-instantiate mode w/ fallback+label.
  LAWS THAT COST US BLOOD - DO NOT RELITIGATE:
    * Receiver URL must SPLIT across httpAddressWithoutQuery/httpAddressQuery.
    * retryInterval='5' not '10000'; adapter boolean dialect is 0/1.
    * Entrypoint paths are TENANT-GLOBAL (collision preflight exists).
    * Sender Participant name = static 'Sender', never a URL path.
    * ONE exchange pattern per artifact; main-process ends are
      message-typed; plain cname::EndEvent only in subprocesses.
    * Oracle verdicts are point-in-time: cool-down after ~10+ deploys/hr.
    * Runtime message ingress lives on the -rt host; designtime host 403s.
  METHOD, ALWAYS: harvest/reference bytes -> mirror verbatim -> unit
    tests -> live oracle single-variable proof -> document -> commit.
- 2026-08-26 (session 8) — SFTP LIFECYCLE: write PROVEN, poll-fetch grammar
  SHIPPED, cadence OPEN:
  * Complete-lifecycle attempt on ONE artifact failed -> ARCHITECTURE
    LAW discovered: CPI iFlows carry ONE exchange pattern; multiple
    sender entrypoints per main process reject at runtime start (3
    fixture starts notwithstanding — unproven elsewhere).
  * oiw_pd_hf now runs the FETCH side standalone: sender.sftp poller
    (52-prop template mirrored verbatim from live DPWORLD_SFTP_QAS,
    cron scheduleKey, noop=delete, file.move=.archive) -> log ->
    ProcessDirect /oiw_pd forward. STARTED.
  * open_mateo_test runs the DROP side: HTTPS POST /open_mateo_test ->
    receiver.sftp OIW-E2E-*.dat. STARTED, message 200, reward 1.0.
  * Live findings banked: (a) sender Participant name must be static —
    path-derived names reject runtime start (regression caught by
    cross-artifact bisect); (b) plain vs message EndEvents differ in
    variant URI (cname::EndEvent vs MessageEndEvent/1.1.0); (c) adapter
    boolean dialect 0/1.
  * OPEN: poll pickup cadence — reference cron mirrors deploy+START but
    no pickup observed within minutes of a dropped file; suspects:
    schedule interval semantics (TIME_INTERVAL rows) or silent
    poll-connect failures. Next session: connectivity-test API probe +
    adjusted cron + longer observation window.
- 2026-08-26 (session 7) — PHASES 0-2 SHIPPED + SFTP LIVE-PROVEN:
  * P0 sharpen: shed list applied; collision preflight + designer-open
    gate in calibrate/CI (ed29537).
  * P1 harvest: oiw emg harvest crawled 300 artifacts across ~71 packages
    -> 59 distinct shapes, 50 exporter gaps nominated (pattern book
    committed). SFTP biggest gap (~70 obs) — operator instinct validated.
  * P2 SFTP: receiver.sftp grammar from harvested SAP_SFTP template;
    UserCredentials deploy verb live-proven (POST /UserCredentials,
    Description required). E2E against REAL etssftp:2232 via Cloud
    Connector using EXISTING trusted known_hosts + AxisBnk_dev saved
    credential (operator call: shared tenant, no known_hosts edits).
  * Live findings banked: (a) internal hosts need proxyType=sapcc +
    locationId (UnknownHost otherwise); (b) adapter boolean dialect is
    0/1 — true/false parsed falsy (compiler bug class); (c) directories
    must pre-exist — autoCreate does NOT mkdir ('No such file').
  Final verdict: POST /oiw_sftp_test -> 200, MPL COMPLETED, file dropped
  to ../../INTERFACE/DP_WORLD/ (existing dir, outside polled INBOUND).
- 2026-08-26 (session 6) — P5b-M1 + P5c-M1 SHIPPED (commit de7eb98):
  * World dynamics: oiw/runtime/world.py — declarative fault scenarios
    (timeout / connection_reset / http_status / malformed / drift)
    compile to the engine mocks seam; HttpReceiver honors injected fails
    with realistic exception types; error propagation exercised e2e.
  * Reward wiring: oiw/tenant/oracle_feedback.py — calibration reports
    map onto the 9-dim reward vector (MPL pass rate = stability;
    STARTED+exercised+all-COMPLETED = completion); failures auto-capture
    as learning sessions; every calibrate report now carries reward:.
  Remaining for P5b: fake SFTP endpoint, schema-drift corpus, scenario
  library per archetype. Remaining for P5c: promotion-workflow hookup
  (record_oracle_outcome into EMG store on PROJECT_APPROVED).
  - PERSISTENCE PROVEN (operator-verified): oiw_var global variable holds
    the exact open-meteo response body (Warsaw 16.4C @ 2026-08-26T07:00)
    — ${body} capture via ProcessDirect hop is byte-faithful. First
    durable side effect produced by an OIW-built multi-artifact chain.
   - State at close: open_mateo_test (path /oiw_pd_hf) and oiw_pd_hf
     (path /oiw_pd_hf2) BOTH STARTED running the identical full chain;
     oiw_pd consuming via ProcessDirect. Next: variables.write live use,
     then P5b world dynamics.
- 2026-08-26 (session 9) — P5a-M2 + P5a-M3 BACKFILLED (calibration floor):
   * M2 SHIPPED: `oiw test --engine real` (default stays simulated). Real
     mode executes true logic and REFUSES loudly (exchange FAILED +
     OIW-REAL-UNSUPPORTED marker) any executed non-endpoint step whose
     plugin declares fidelity=simulated — sender./receiver.* are exempt
     (mock seam = world dynamics, P5b). New runtime/mpl.py emits MPL-shaped
     records from local runs: same field names/status vocabulary as the
     tenant API (/Date(ms)/ LogStart/LogEnd wrapper, COMPLETED/FAILED),
     provenance-marked Origin=local-sim.
   * M3 SHIPPED: `oiw parity` — corpus manifest (packages/parity-corpus/
     manifest.yaml) → local real-engine run per case vs CACHED calibration
     report (never CI; stale-oracle detection per maxOracleAgeHours).
     Verdicts: agreed | mismatched | pending-oracle | stale-oracle |
     unsupported | no-local-tests. Publishes docs/emg/sim-parity.yaml with
     agreement ratio + gate (≥90%, min 10 comparable). Gate NOT auto-enforced
     in v0 (--enforce-gate opts in).
   * First published number is honest-ugly: 1 comparable case (held-out-
     order-async), tenant side is the wedge-era ERROR verdict (01:54, blood
     law #6 applies) ⇒ mismatch, ratio 0.0, gate false. order-to-s4 local =
     UNSUPPORTED in real engine (transform.xslt is XSLT1-only stub);
     sftp-order-drop UNSUPPORTED (splitter/gather stubs). These refusals are
     the instrument working, not failures of it.
   * NEXT: fresh oracle runs to replace wedge-era reports; then Phase B
     breadth (Mapping first) inside the measured harness.

- 2026-09-02 — P6 EXECUTION LOG (live, this session):
  * Bisection matrix (all via calibrate loop, seconds-fast):
    | Variant | Verdict |
    |---|---|
    | bare RR + plain EndEvent | START-FATAL (plain main-process end) |
    | RR + PD terminator | STARTED; "No consumers" until listener deployed |
    | RR + PD + companion listener | **STARTED + message 200 + MPL COMPLETED both** |
    | + converter.json-to-xml (rung 3) | STARTED; message fails 'Member name not found' |
    | converter addXMLRootElement=false (rung 4) | still fails — converter shape unproven, pulled from pieces |
    | EndEvent-form receiver (GSTR2A-style) | every message 'Member name not found'; GSTR2A/B/Auth have ZERO MPL rows |
  * CREATE verb live-proven: POST entity WITHOUT Version (400 if present; auto-generated).
  * Configurations: nav POST = 501 (read-only); parameters.prop in the bundle auto-creates rows on upload.
  * Variables truth: encrypt='true', componentVersion='1.2' (false/absent = start ERROR).
  * Listener truth: sender-only flows carry empty Participant_2 'Receiver' + MessageEndEvent end.
  * Turbo idempotency bug found+fixed live (flow.create on existing id).
