# WP-10 Task Board — Sprint 2 (H7–H12)

> **For the frontend engineer.** Issued 2026-09-03 after sprint-1 (H1–H6) integration
> (commit `0120c2b`) and the operator's capacity call. Backend runs phases 1–5
> (multi-package oracle legs, sftp leg, encoder harvest, B-3 Mapping) in parallel —
> see "Conflict surface" per task for the declared partition.
>
> **Rules carried from WP-10 §2/§6 (unchanged):** acceptance criteria are the review
> contract; WP-09 §2.4 safety rules verbatim (no tenant creds — everything here is
> local + committed fixtures; fixture workspaces in `/tmp`; never commit `.oiw/` state
> except the listed committed artifacts; one PR per task, task ID in the message +
> log entry appended per PR).

---

## H7 — `encoder.base64` exporter shape *(START HERE — operator call)*

**Unblocks:** `payload-enricher-fwd` parity case (currently honest-pending), good-first-issue #2.

**⚠️ HARVEST LANDED (2026-09-03, backend) — read this before implementing:**
The harvest scanned all 600 tenant bundles for the encode/decode family. **The
live truth:** the ONLY observed member is **`activityType=Decoder`,
`encoderType=Base64 Decode`**, `cname::Base64 Decode/version::1.0.1`,
`componentVersion=1.0` — seen in exactly 2 flows (both committed as the reference:
`packages/pattern-book/shapes/Decoder-Base64Decoder.yaml`, customer-content
license, reference-only). **There is NO Encoder activityType anywhere on the
tenant** — encode-direction has zero precedent.

**Revised honest scope:**
1. Map `encoder.base64` → activityType `Decoder` when the node config's
   direction is **decode**; emit the reference property set VERBATIM
   (`componentVersion=1.0`, `cmdVariantUri=...cname::Base64 Decode/version::1.0.1`,
   `encoderType=Base64 Decode`).
2. Direction **encode (or absent)** → **raise loudly** ("no live-proven Encoder
   shape on the tenant — refuse to guess; needs a reference bundle"). The
   honesty floor outranks the convenience; `payload-enricher-fwd`'s example
   flow must therefore use direction=decode to become buildable — flag that
   example edit to backend for review (it changes a parity-case project).
3. Unit tests both ways: decode builds; encode raises. Plus the verbatim
   property-set assertion against the reference YAML.

**Context:** The runtime plugin exists (`apps/cli/oiw/runtime/steps/encoder_base64.py`,
fidelity=compatible-subset) but `sap_export.py` has NO CPI mapping — `oiw build`
refuses to emit a bundle containing an encoder node ("no designer-proven CPI
mapping"). The METHOD (always): **harvest reference bytes → mirror verbatim →
unit tests**.

**Files:** `apps/cli/oiw/compiler/sap_export.py` (encoder branch + `_OIW_TO_ACTIVITY`
entry ONLY — see partition below), `apps/cli/tests/test_sap_export_v6_shapes.py`
(new test class or sibling file).

**Acceptance:**
1. `_OIW_TO_ACTIVITY` maps `encoder.base64` → the reference's exact activityType
   string (from the harvested shape YAML — do not guess; if the reference says
   e.g. `Encoder` with cmdVariantUri `.../cname::Encoder/version::X.Y.Z`, mirror both).
2. Emitter branch produces the reference's full `ifl:property` row set VERBATIM
   (constant values from the reference; config-driven values — encode vs decode
   direction — from node config).
3. Unit tests: a flow with an encoder node builds; the emitted rows match the
   reference property set key-for-key; unknown config directions fail loudly
   (refuse, never invent).
4. `oiw build --project examples/payload-enricher-fwd` produces a bundle (digest
   deterministic — rebuild and compare, the repo convention).
5. `oiw validate --strict` + `oiw test --all --engine real` on that example stay green.

**Partition (declared):** backend is running B-3 Mapping breadth in `sap_export.py`
in parallel. Your changes stay ISOLATED to: the `_OIW_TO_ACTIVITY` map entry +
ONE new `elif activity == ...` emitter branch + the Script/resource-style helper
ONLY IF the encoder needs config resolution (unlikely — mirror the converters'
pattern). No edits to Mapping/XSLT branches, `build_cpi_bundle`, or header/DI
generation. Conflicts, if any, resolve at merge on your side.

---

## H8 — Interpreter splitter-phrasing gap (roadmap open thread #5)

**Context:** live-found: "split the batch" doesn't map to `splitter.general` —
EMG retrieval returns conf 0.000 (honest, but the requirement should assemble).
The keyword map lives in `apps/cli/oiw/agent/interpreter.py` (~line 184:
`"split": ["split", "splitter"]`) — phrasings like "batch", "each order",
"per item", "split the batch" don't hit.

**Files:** `apps/cli/oiw/agent/interpreter.py`, `apps/cli/oiw/agent/normalization.py`
(check `normalization.py` line ~115 "splitter" component vocabulary too),
`apps/cli/tests/agent/test_interpreter.py`.

**Acceptance:**
1. Requirements phrased "split the batch", "process each item", "split orders
   into individual messages" all yield a `splitter.general` component.
2. Negative controls: "split the difference", "split tunneling" do NOT (avoid
   over-triggering; a word-boundary/pattern test for each added keyword).
3. End-to-end: `assemble_from_requirement` on a splitter+forward requirement
   produces the piece chain (mock world config), OR escalates honestly if
   splitter is not in the proven-piece set at test time — write the test
   against whichever the piece library currently holds, and assert WHICH.
4. Existing interpreter tests untouched and green.

---

## H9 — Absorb ServiceTask classification (thread #5's other half)

**Context:** absorbed tenant chains still carry unclassified ServiceTask entries,
so EMG injection over-fires the OIW-I002 piece-assembly fallback. The task:
classify `ExternalCall` serviceTasks as mid-flow `receiver.http` in absorb's
IR builder (the roadmap's exact note: "classify ExternalCall serviceTasks as
mid-flow receiver.http in absorb's IR builder").

**Files:** `apps/cli/oiw/tenant/absorb.py`, `apps/cli/tests/test_absorb.py`.

**Acceptance:**
1. An absorb fixture (synthetic `.iflw` content with an ExternalCall
   serviceTask carrying the standard ExternalCall properties) produces an IR
   node `receiver.http` (not an unclassified stub).
2. Chains that become fully-piece-covered after reclassification NO LONGER
   trip OIW-I002 in the turbo injection path (test the boundary directly:
   one fixture that flips, one that still legitimately falls back).
3. Non-ExternalCall serviceTasks stay unclassified (honest) — no
   over-classification.
4. Existing absorb tests green (5 tests).

---

## H10 — `oiw simulate` CLI verb (good-first-issue #7)

**Context:** the engine + trace exist (the web UI uses them via the simulate
API); terminal users have no one-shot command.

**Files:** `apps/cli/oiw/cli.py` (new `simulate` command), `apps/cli/tests/`
(new test file; follow `test_calibrate_runtime.py`'s sys.path style if needed).

**Acceptance:**
1. `oiw simulate --project <p> --flow <f> --test smoke` runs the real engine
   against the FlowTest named `smoke` and prints per-step trace entries
   (pass/fail + duration) + final exchange status; exit 0 on COMPLETED, 1 on
   FAILED, 2 on usage errors.
2. `--json` flag emits the full structured trace (same shape as the simulate
   API payload — reuse the serializer, don't fork it).
3. `--engine real|simulated` flag (default simulated, matching `oiw test`).
4. MPL-shaped records emitted under `--engine real` (the `runtime/mpl.py`
   path) — assert `Origin=local-sim` in the test.
5. No tenant access, no network (mock seam) — simulate is local-only by design.

---

## H11 — FlowTest assertion types (good-first-issues #5 + #6)

**Files:** `apps/cli/oiw/testing.py` (`_check_assertion`), FlowTest JSON schema
(`packages/ir-schema/` — locate the FlowTest schema and extend the enum/oneOf),
`apps/cli/tests/` (assertion tests).

**Acceptance:**
1. `outbound.header.equals` — target, name, equals — asserts an outbound mock
   call's request header (works in both engines; the trace records outbound
   requests already).
2. `property.contains` — substring assertion on an exchange property.
3. Schema validation accepts both new types (`oiw validate` on a flow test
   using them passes).
4. Unknown assertion types keep failing loudly (unchanged behavior).
5. At least one example flow's test uses each new assertion type (edit
   `examples/oiw-conv-fwd/.../smoke.yaml` or a new example — must stay green).

---

## H12 — More parity-example projects (rolling)

**Context:** backend now deploys oracle legs into THREE rotating scratch
packages (TestOIW, OIWtest, AdequareGST — the per-package throttle lesson),
so every example you land converts to a comparable parity case same-session.

**Files:** `examples/<new-id>/` (mirror `examples/weather-logger-async`
structure), `packages/parity-corpus/manifest.yaml` (pending-oracle entries).

**Rules:** PROVEN shapes ONLY (what's in `_OIW_TO_ACTIVITY` + RR/PD/HTTP
endpoints; consult `packages/law-registry/tenant-laws.yaml` for placement
laws); unique entrypoint path + PD address per project (tenant-global);
`converter.json-to-xml` must sit after an RR (law-r4, ratified). NO
transform.xslt / splitter / gather / encoder until B-3/H7 merge (they have no
live-proven exporter shape or are mid-flight).

**Acceptance per project:** `oiw validate --strict` clean; `oiw test --all
--engine real` PASS; manifest entry added with `test:` name; README states
the chain. Backend converts to comparable via calibrate (the oracle leg is
backend's, never yours).

---

## Suggested order

H7 (if harvest landed) → H8 → H9 → H10 → H11 → H12 rolling. H10/H11 are
fully independent — parallelizable with anything. PR per task; task ID in
the commit message; log entry per PR.

## What NOT to do (sprint-2 additions)

| Temptation | Why not |
|------------|---------|
| Guess the encoder activityType without the harvested reference | The METHOD is verbatim-mirror; a guessed shape deploys a broken designer artifact (blood law: mirror reference bytes) |
| Touch `sap_export.py` beyond the declared H7 partition | Backend's B-3 Mapping work lives there this sprint; the partition keeps merges mechanical |
| Add splitter/gather/xslt/encoder to parity examples | Splitter/gather exporter shapes are unproven for round-trips (H4/H5 were runtime-only); xslt is B-2 |
| Commit calibration reports for your examples | Oracle legs are backend's (tenant creds never travel to you) |

---

## NEW FINDINGS for the board (backend session, 2026-09-03 evening)

1. **`sftp-order-drop` ALSO blocked on a missing exporter shape:** its
   `validator.json-schema` node has no CPI mapping (same family as H7's
   encoder). The corpus scan found **no Validator/Schema activityType
   anywhere** — same situation as Encoder. Natural follow-up task (H13,
   below): harvest hunt or honest-refusal decision.

## H13 — `validator.json-schema` exporter shape decision *(new)*

**Files:** `apps/cli/oiw/compiler/sap_export.py` (isolated branch + map entry,
same partition as H7), tests.

**Acceptance:**
1. Scan decision first: the corpus shows NO live Validator shape. Either
   (a) find a tenant flow with schema-validation semantics under a
   DIFFERENT activity name (check `contentEnricherWithLookup`, `Filter`
   dialects — coordinate with backend, tenant reads are backend's), or
   (b) implement honest refusal for validator nodes with a clear
   remediation message + a `--engine simulated`-only note.
2. If (b): unit test the refusal; `sftp-order-drop` stays honest-pending
   until a reference is found (log it in the case's README).
