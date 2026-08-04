# Work Package WP-07: Real EMG Learning — Failed-to-Expert Trajectory Pairs from Genuine Development Sessions

**Phase:** Pre-Tenant Knowledge Foundation
**Prerequisite:** WP-06 complete (506 tests, 6 CI workflows green, seed corpus populated, EMG Phase B+C operational)
**Spec sections:** §15.7, §15.8, §15.9, §15.10, §15.11, §15.12, §15.19
**Branch convention:** `feature/wp07-<track>-<task-number>`
**SDK LLM:** Available via z-ai CLI. Use for roadblocks, requirement generation, trajectory review, and failure-mode research.

---

## 1. Objective

Make the EMG learn from **genuine engineering experience** before any tenant work begins. Specifically:

1. Ingest **real public SAP integration artifacts** (not synthetic variations) to ground the knowledge base in patterns that real humans built.
2. Create **failed-to-expert trajectory pairs** through guided development sessions where the agent attempts a task, fails, and a human corrects it.
3. Extract **graph edit paths** from those pairs — the actual correction knowledge that makes the system smarter.
4. Build **cross-task edges** from diverse real artifacts so the EMG discovers transferable patterns.
5. **Prove measurable improvement**: the agent performs better on held-out tasks after learning than before.

This work package answers the circularity problem: the EMG will no longer be learning from artifacts the system generated from its own understanding. It will learn from real artifacts, real mistakes, and real corrections.

---

## 2. Why This Must Happen Before the Tenant

The tenant adds one dimension to the reward vector (`deployment_success`) and one source of evidence (differential testing). But expert trajectory eligibility (§15.7) does **not** require tenant deployment:

> "An expert trajectory is eligible only when: Required tests pass. Validation and security policies pass. Compatibility status is recorded. **A qualified reviewer approves it.** Confidentiality policy permits memory extraction. The task and repository revisions are immutable. The outcome has not later been marked as causing a regression."

Five of those seven conditions are achievable locally. The most important one — **reviewer approval** — is a human judgment call that doesn't need a tenant. The EMG's knowledge quality is determined by the diversity and authenticity of its trajectories, not by deployment gates.

Build the knowledge first. Deploy it later.

---

## 3. Current State and Gaps

| What Exists | What's Missing for Real Learning |
|-------------|----------------------------------|
| 50 synthetic trajectories (all "expert") | No **failed** trajectories — no correction knowledge exists |
| Graph edit path extractor works | No actual edit paths extracted (nothing failed vs. expert to compare) |
| Cross-task edges can be built | Only 5 archetype patterns; no diversity |
| Retrieval wired into orchestrator | Nothing meaningful to retrieve (synthetic patterns only) |
| EMG evaluation tests pass | No before/after comparison showing improvement |
| TF-IDF embeddings work | No diverse requirement corpus to embed against |
| SDK LLM available via z-ai | Not yet used for guided learning sessions |

**The fundamental gap:** The EMG has the machinery but no genuine knowledge. It's a library with shelves and a cataloging system but no books. This work package fills the shelves with real books.

---

## 4. The Learning Loop This Work Package Implements

The EMG paper's core mechanism is:

```
Failed trajectory G  ──┐
                       ├──> Graph matching ──> Edit path ──> Correction insight
Expert trajectory G* ──┘
```

Right now, the repo has **zero** failed-to-expert pairs. All 50 trajectories are synthetic "expert" trajectories generated from finished artifacts. There's no correction knowledge.

This work package creates the pairs:

```
Session 1: Agent attempts "Add OData pagination to receiver" → FAILS (forgets maxPages)
           Developer corrects → adds maxPages bound
           EMG extracts: "after add-node receiver.odata-v4, INSERT set-config maxPages"
           
Session 2: Agent attempts "Add retry to SOAP receiver" → FAILS (retries non-idempotent POST)
           Developer corrects → adds idempotency check
           EMG extracts: "after add-node receiver.soap with method=POST, INSERT add-idempotency-guard"

Session N: Agent attempts similar task → EMG retrieves correction → agent succeeds first try
           → Learning proven
```

Each session produces one failed trajectory, one expert trajectory, and one graph edit path. After 20 sessions, the EMG has 20 corrections. After 50 sessions, it has 50 corrections covering common failure modes. That's real knowledge.

---

## 5. Track A: Real Public Artifact Ingestion

### Objective

Replace the synthetic seed corpus foundation with real SAP integration artifacts from public sources. This gives the EMG patterns that real humans built for real reasons.

### Task A-001: SAP CodeJam Full Ingestion

The CodeJam repo was cloned during P1b (`packages/test-fixtures/real-sap/sap-codejam-request-employee-dependants/`). Only one artifact was imported. Scale to all exercises.

**What to do:**

1. Clone the full CodeJam repo if not already present:
   ```bash
   git clone https://github.com/SAP-samples/connecting-systems-services-integration-suite-codejam /tmp/sap-codejam
   ```

2. Identify all iFlow artifacts in the repo (search for `.iflw` files, `src/main/resources/scenarioflows/` directories, or ZIP packages).

3. For each artifact:
   - Run `oiw import` (use the existing import parser)
   - Run `oiw validate --strict`
   - If validation passes: ingest into `packages/seed-corpus/artifacts/codejam-{exercise-id}/`
   - If validation fails: record the failure mode (this is itself useful knowledge — log what the import parser couldn't handle)

4. Generate expert trajectories from each successfully imported artifact using the existing `synthesize_expert_trajectory()` function.

5. Promote all through the pipeline.

**Expected yield:** 8-15 real CodeJam artifacts with diverse patterns (HTTP, SOAP, OData, Groovy, XSLT, routing, error handling).

**SDK LLM usage:** If the import parser fails on a CodeJam artifact, ask the LLM to analyze the artifact structure and identify what's missing from the parser. This is a real roadblock that the LLM can help resolve.

**Acceptance:**
- [ ] ≥ 8 real CodeJam artifacts imported and validated
- [ ] Each produces a trajectory with `provenance.source = "sap-codejam"`
- [ ] Import failures documented with specific parser gaps
- [ ] All trajectories promoted to PROJECT_APPROVED

### Task A-002: SAP API Hub Sample Packages

The SAP Business Accelerator Hub (api.sap.com) hosts public integration packages under SAP Sample Code License.

**What to do:**

1. Identify 5-10 downloadable integration packages from api.sap.com that match the adapters already implemented (HTTP, SOAP, OData, Mail, IDoc).

2. Download each package (they're ZIP files with iFlow XML, scripts, mappings).

3. License audit: confirm SAP Sample Code License permits tooling use.

4. Import, validate, and ingest each package.

5. Generate expert trajectories.

**Expected yield:** 5-10 production-grade integration patterns with real Groovy scripts, real XSLT mappings, real adapter configurations.

**SDK LLM usage:** If a package uses an adapter not yet implemented (e.g., SuccessFactors, JMS), ask the LLM to describe what the adapter does so you can decide whether to stub it or skip the artifact.

**Acceptance:**
- [ ] ≥ 5 API Hub packages imported
- [ ] License audit documented per package
- [ ] Trajectories generated and promoted
- [ ] Packages using unimplemented adapters either stubbed or documented as opaque

### Task A-003: GitHub Community Artifacts

**What to do:**

1. Search GitHub for repos with SAP CPI content:
   ```bash
   # Search for repos with SAP CPI iFlows
   gh search repos "sap cpi iflow" --limit 20
   gh search repos "cloud integration iflow" --limit 20
   gh search repos "sap integration suite sample" --limit 20
   ```

2. For each promising repo:
   - Check LICENSE (must be Apache-2.0, MIT, BSD, or SAP Sample Code)
   - Scan for secrets (gitleaks)
   - Import artifacts

3. Apply the same pipeline: import → validate → ingest → synthesize → promote.

**Expected yield:** 5-10 additional diverse artifacts from community sources.

**SDK LLM usage:** Use the LLM to quickly assess whether a repo contains usable artifacts before spending time on manual review. Ask it to identify the integration pattern, adapters used, and complexity level.

**Acceptance:**
- [ ] ≥ 5 community artifacts imported
- [ ] All license-audited
- [ ] All secret-scanned
- [ ] Trajectories generated and promoted

### Task A-004: SAP Blog Post Patterns

SAP Community blog posts frequently include iFlow XML snippets, Groovy scripts, and XSLT mappings.

**What to do:**

1. Identify 5-10 SAP Community blog posts that include complete or near-complete integration patterns. Search for:
   - "SAP CPI Groovy script examples"
   - "SAP Cloud Integration XSLT mapping tutorial"
   - "SAP CPI error handling pattern"
   - "SAP CPI retry idempotency"
   - "SAP CPI content-based router example"

2. Extract the code artifacts (Groovy scripts, XSLT mappings, flow configurations).

3. Wrap each into a minimal OIW project (flow.yaml + resources) that exercises the pattern.

4. Import, validate, ingest, synthesize, promote.

**Expected yield:** 5-10 pattern-focused artifacts that capture specific integration techniques.

**SDK LLM usage:** This is where the LLM is most valuable. Ask it to:
- Summarize what each blog post pattern does
- Identify the integration archetype (api-to-erp, file-to-api, paginated-ingestion, etc.)
- Generate the flow.yaml structure from the blog post description
- Write the Groovy/XSLT code if the blog post describes it but doesn't include it

**Acceptance:**
- [ ] ≥ 5 blog-post-derived patterns ingested
- [ ] Each tagged with its archetype
- [ ] All produce valid trajectories
- [ ] Patterns cover at least 3 different archetypes

---

## 6. Track B: Guided Learning Sessions (Failed-to-Expert Pairs)

### Objective

Create genuine failed-to-expert trajectory pairs through structured development sessions. This is the core of the work package. Each session produces correction knowledge that the EMG can retrieve in the future.

### The Session Protocol

Each learning session follows this exact sequence:

```
1. REQUIREMENT: Define a realistic integration task (natural language)
2. ATTEMPT: The agent (via oiw agent or z-ai CLI) attempts the task autonomously
3. FAILURE: The attempt fails or produces a suboptimal result (validation error, 
             test failure, missing step, wrong configuration)
4. OBSERVATION: Record the failure mode (diagnostic code, test output, 
                what went wrong)
5. CORRECTION: The developer (acting as expert reviewer) fixes the failure
6. EXPERT TRAJECTORY: Record the corrected implementation as the expert path
7. PAIRING: Link the failed trajectory to the expert trajectory
8. EXTRACTION: Run graph matching to produce the edit path
9. PROMOTION: Promote the correction through the pipeline
10. VERIFICATION: Present the same (or similar) requirement again and verify 
                  the agent now succeeds using the retrieved correction
```

### Task B-001: Learning Session Infrastructure

**What to build:**

New CLI commands for managing learning sessions:

```bash
# Start a learning session
oiw learn start --requirement "Add OData pagination to the S/4 receiver" --project examples/order-to-s4

# Record the agent's attempt (auto-captured during execution)
oiw learn record-attempt --session <session-id>

# Record the failure (what went wrong)
oiw learn record-failure --session <session-id> --diagnostic "OIW-E003: unbounded pagination" --details "..."

# Record the human correction (what the expert did)
oiw learn record-correction --session <session-id> --actions '[{"tool": "flow.patch", "op": "updateNodeConfig", ...}]'

# Finalize the session (pairs failed + expert trajectories)
oiw learn finalize --session <session-id>

# Extract the edit path and store the correction
oiw learn extract --session <session-id>

# Verify learning (re-run the same requirement, check if correction is retrieved)
oiw learn verify --session <session-id>
```

**New module:** `apps/cli/oiw/learn/`

```
apps/cli/oiw/learn/
├── __init__.py
├── session.py          # LearningSession dataclass + lifecycle management
├── recorder.py         # Captures agent attempts and failures
├── corrector.py        # Records human corrections as expert trajectories
├── pairer.py           # Links failed + expert trajectories, runs graph matching
├── verifier.py         # Re-runs requirement to verify correction is retrieved
└── cli.py              # CLI command handlers
```

**LearningSession dataclass:**

```python
@dataclass
class LearningSession:
    id: str                          # session-001
    requirement: str                 # "Add OData pagination to the S/4 receiver"
    normalized_requirement: dict     # intent, operations, components
    project_id: str                  # which project this runs against
    flow_id: str                     # which flow
    status: str                      # IN_PROGRESS | FAILED_RECORDED | CORRECTED | PAIRED | EXTRACTED | VERIFIED
    
    # The failed attempt
    failed_trajectory_id: str | None
    failure_diagnostic: str | None   # "OIW-E003: unbounded pagination"
    failure_details: str | None
    
    # The expert correction
    expert_trajectory_id: str | None
    correction_actions: list[dict]   # what the expert did differently
    
    # The extracted knowledge
    edit_path_id: str | None
    insight_id: str | None
    
    # Verification
    verification_result: str | None  # "agent retrieved correction and succeeded"
    
    created_at: float
    completed_at: float | None
```

**Tests (minimum 6):**
- Session lifecycle: start → record → finalize → extract → verify
- Failed trajectory captured correctly
- Expert trajectory captured correctly
- Pairing links both trajectories
- Edit path extracted from pair
- Verification confirms retrieval

### Task B-002: Failure Mode Catalog

Before running sessions, define the failure modes you want the agent to encounter. These should be **realistic** — things that actual SAP CPI consultants get wrong.

**What to build:** `packages/seed-corpus/failure-modes.yaml`

```yaml
apiVersion: oiw.dev/v1alpha1
kind: FailureModeCatalog
metadata:
  version: 0.1.0
spec:
  failureModes:
    - id: fm-001
      name: "Missing pagination bound"
      archetype: paginated-api-ingestion
      description: "Agent adds OData receiver without maxPages limit"
      diagnostic: "OIW-E003"
      correction: "Add maxPages config to receiver.odata-v4"
      severity: high
      
    - id: fm-002
      name: "Retry without idempotency"
      archetype: api-to-erp
      description: "Agent adds retry to POST receiver without idempotency key"
      diagnostic: "OIW-W003"
      correction: "Add idempotency key header before retry"
      severity: high
      
    - id: fm-003
      name: "Missing error subprocess"
      archetype: any
      description: "Agent creates flow without exception handling"
      diagnostic: "OIW-W002"
      correction: "Add errorHandling.defaultExceptionSubprocess"
      severity: medium
      
    - id: fm-004
      name: "Inline secret in receiver config"
      archetype: any
      description: "Agent puts password directly in receiver URL"
      diagnostic: "OIW-E002"
      correction: "Replace with credentialRef"
      severity: critical
      
    - id: fm-005
      name: "Missing schema resource"
      archetype: api-validation
      description: "Agent adds validator.json-schema but doesn't create the schema file"
      diagnostic: "RESOURCE_NOT_FOUND"
      correction: "Create the referenced schema resource"
      severity: high
      
    - id: fm-006
      name: "Wrong edge target after inserting node"
      archetype: any
      description: "Agent inserts node but doesn't reconnect edges"
      diagnostic: "DANGLING_EDGE"
      correction: "Replace edge from sender→old_target with sender→new_node→old_target"
      severity: medium
      
    - id: fm-007
      name: "Groovy script uses blocked class"
      archetype: any
      description: "Agent writes Groovy that imports java.net.URL"
      diagnostic: "SANDBOX_VIOLATION"
      correction: "Use allowed HTTP client or externalize the call"
      severity: critical
      
    - id: fm-008
      name: "Missing timeout on receiver"
      archetype: any
      description: "Agent adds receiver without timeoutSeconds"
      diagnostic: "OIW-W001"
      correction: "Set timeoutSeconds to 30"
      severity: low
      
    - id: fm-009
      name: "Content-Type mismatch after transformation"
      archetype: transform-pipeline
      description: "Agent transforms XML→JSON but doesn't update Content-Type header"
      diagnostic: "CONTENT_TYPE_MISMATCH"
      correction: "Add Content Modifier to set Content-Type: application/json"
      severity: medium
      
    - id: fm-010
      name: "Missing externalized parameter"
      archetype: any
      description: "Agent hardcodes tenant URL in receiver config"
      diagnostic: "OIW-W005"
      correction: "Replace with ${ENV_VAR} reference"
      severity: medium
```

**SDK LLM usage:** Ask the LLM to review this catalog and suggest additional failure modes based on common SAP CPI mistakes. Prompt: *"What are the 10 most common mistakes SAP CPI consultants make when building integration flows? For each, describe the failure mode, the diagnostic that would catch it, and the correction."*

**Acceptance:**
- [ ] ≥ 10 failure modes catalogued
- [ ] Each has a realistic diagnostic code
- [ ] Each has a specific correction action
- [ ] Catalog covers at least 4 different archetypes
- [ ] LLM-reviewed for additional modes

### Task B-003: Guided Learning Sessions (Batch 1 — 10 Sessions)

**What to do:**

Run 10 learning sessions, each targeting a different failure mode from the catalog. For each session:

1. **Set up the scenario:** Create a project state where the failure is likely to occur. For example, for fm-001 (missing pagination bound), create a flow with an OData receiver that has no maxPages.

2. **Run the agent:** Execute `oiw agent "<requirement>"` with the EMG retriever disabled (so it doesn't cheat by retrieving corrections that don't exist yet).

3. **Capture the failure:** The agent should produce a suboptimal result. Record:
   - The full trajectory (all typed actions and observations)
   - The specific diagnostic that fired
   - What the agent did wrong

4. **Apply the correction:** As the developer/reviewer, fix the issue manually. Record:
   - The corrective actions taken
   - The corrected trajectory

5. **Finalize and extract:** Run the pairing and extraction pipeline.

6. **Verify:** Re-run the same requirement with the EMG retriever enabled. Verify the agent retrieves the correction and succeeds.

**Session script (example for fm-001):**

```bash
# 1. Set up scenario
oiw init /tmp/learn-fm-001 --archetype paginated-api-ingestion
# Create a flow with an OData receiver missing maxPages

# 2. Run agent WITHOUT EMG (baseline)
oiw agent "Add pagination handling to the OData receiver" \
  --project /tmp/learn-fm-001 \
  --mode autonomous \
  --no-emg  # Disable retrieval to get a genuine failure

# 3. Observe failure: agent adds receiver without maxPages
#    Diagnostic: OIW-E003 fires

# 4. Record the failure
oiw learn record-failure --session fm-001-session-1 \
  --diagnostic "OIW-E003" \
  --details "Agent added receiver.odata-v4 without maxPages bound"

# 5. Apply correction manually
oiw agent "Set maxPages to 100 on the OData receiver" \
  --project /tmp/learn-fm-001 \
  --mode autonomous

# 6. Record the correction
oiw learn record-correction --session f