# Work Package WP-05: Tenant Deployment Pipeline & EMG Intra-Task Memory

**Phase:** Phase 4 (Tenant Sync & CI/CD) + EMG Phase B (Intra-Task Correction)
**Estimated effort:** 15–20 working days
**Prerequisite:** WP-04 fully merged (Tasks 1-9, 317 tests, CI green)
**Spec sections:** §18 (Tenant Connectivity), §15.3–15.9 (EMG Phase B), §22 Phase 4 exit criteria
**Branch:** `feature/wp05-tenant-deploy-emg-phase-b`

---

## 1. Objective

Dual-track delivery:

**Track A (Phase 4):** Build the tenant deployment pipeline so consultants can safely promote artifacts from Git to real SAP Cloud Integration tenants. This closes the loop from "develop locally" to "deploy to production" and provides the `deploymentSuccess` / `runtimeStability` dimensions needed by the EMG reward vector.

**Track B (EMG Phase B):** Build the mechanical graph-matching core that converts recorded trajectories into reusable intra-task correction memory. This is where the "TurboVLA-style mechanics" begin — replacing LLM planning with deterministic graph retrieval for known patterns.

After this work package, the system satisfies:

- **Spec §22 Phase 4 exit criteria:** A reviewed Git commit can be deployed to a development tenant. Drift prevents accidental overwrite. Deployment is auditable.
- **Spec §22 Phase 5 partial exit (intra-task):** Failed implementations produce machine-readable correction paths against approved expert trajectories. Full trajectories are reproducibly reconstructed from recorded events.

The critical strategic outcome: by the time enough trajectories accumulate for EMG Phase C (cross-task transfer), the deployment pipeline will be providing real outcome signals, and the mechanical graph matcher will be ready to consume them.

---

## 2. Current State (What Exists)

| Component | Location | Status |
|-----------|----------|--------|
| Project IR + Flow IR | `apps/cli/oiw/` | ✅ Stable |
| Compatibility compiler | `apps/cli/oiw/build/` | ✅ Import/export works for minimal fixtures |
| Export to SAP-compatible ZIP | `oiw build` command | ✅ Deterministic |
| Trajectory recorder | `apps/cli/oiw/agent/trajectory.py` | ✅ WP-04 Task 4, persists to `.oiw/trajectories/` |
| Action/observation normalization | `apps/cli/oiw/agent/normalization.py` | ✅ Stable 5-tuples |
| Redaction | `apps/cli/oiw/agent/redaction.py` | ✅ 9 regex + 16 key-based patterns |
| Reward vector | `apps/cli/oiw/agent/orchestrator.py` | ⚠️ 4 dimensions (needs 9 per spec §15.8) |
| Tenant adapter | — | ❌ Does not exist (OW-005) |
| Deployment state machine | — | ❌ Does not exist |
| Drift detection | — | ❌ Does not exist |
| Action Decision Graph builder | — | ❌ Does not exist (EMG Phase B) |
| Graph matching (exact/rule) | — | ❌ Does not exist |
| Common subgraph / edit path | — | ❌ Does not exist |
| Memory promotion workflow | — | ❌ Does not exist |
| Full SPA decomposition | `apps/web/src/App.tsx` | ⚠️ Monolithic (OW-029) |

---

## 3. Deliverables

### Track A: Tenant Deployment Pipeline (Phase 4)

#### Task 1: Tenant Connection Profiles

**New IR kind:** `EnvironmentProfile` (already defined in spec §7.5, now implement)

```yaml
apiVersion: oiw.dev/v1alpha1
kind: EnvironmentProfile
metadata:
  name: dev
spec:
  target: sap-cloud-integration-2026-07
  tenantUrl: ${DEV_TENANT_URL}
  auth:
    method: oauth2-client-credentials
    tokenUrl: ${DEV_TOKEN_URL}
    clientId: ${DEV_CLIENT_ID}
    credentialRef: sap-dev-api-client
  externalizedParameters:
    S4_BASE_URL: https://s4-dev.example.com
  deploymentPolicy:
    requiresApproval: true
    approvers: [integration-lead]
    autoVerify: true
    approvalTtlHours: 24
```

**Files:**
- `apps/cli/oiw/environments.py` — load, validate, resolve profiles
- `apps/cli/oiw/schemas/environment-profile.json` — JSON Schema
- `examples/order-to-s4/environments/dev.yaml`, `test.yaml`, `prod.yaml` — sample profiles

**Tests (minimum 4):**
- Load profile with env var substitution
- Reject profile with inline secret values
- Validate required fields (target, tenantUrl, auth)
- Reject profile referencing unknown credentialRef

#### Task 2: Tenant Adapter Interface + SAP CI Mock

**What to build:** A pluggable tenant adapter interface. The MVP implementation is a **mock SAP CI tenant** (for local/CI testing). A real SAP CI adapter is gated on OW-010 (tenant access).

```python
# apps/cli/oiw/tenant/adapter.py

class TenantAdapter(Protocol):
    async def connect(self, profile: EnvironmentProfile) -> None: ...
    async def get_artifact_version(self, package_id: str) -> ArtifactVersion: ...
    async def get_artifact_digest(self, package_id: str) -> str | None: ...
    async def upload_package(self, package_id: str, archive: bytes, digest: str) -> UploadResult: ...
    async def deploy(self, package_id: str, version: str) -> DeploymentResult: ...
    async def poll_deployment(self, deployment_id: str) -> DeploymentStatus: ...
    async def get_runtime_logs(self, package_id: str, since: datetime) -> list[LogEntry]: ...
    async def disconnect(self) -> None: ...

# apps/cli/oiw/tenant/mock_adapter.py
class MockSapCiTenantAdapter:
    """In-memory mock for testing. Persists state to .oiw/mock-tenant/{profile}.json."""
    # Implements full TenantAdapter protocol
    # Validates archive structure (must have MANIFEST.MF, iFlow XML, etc.)
    # Simulates deployment latency (1-3 seconds)
    # Simulates deployment failures based on configurable scenarios

# apps/cli/oiw/tenant/sap_ci_adapter.py (stub)
class SapCiTenantAdapter:
    """Real SAP CI adapter — requires OW-010 tenant access to implement."""
    async def connect(self, profile):
        raise NotImplementedError(
            "SAP CI tenant adapter not yet implemented. "
            "See OW-010. Use mock adapter for testing."
        )
```

**Mock adapter features:**
- Persists uploaded artifacts to `.oiw/mock-tenant/{profile}/artifacts/`
- Tracks deployment state machine
- Configurable failure scenarios (auth failed, package invalid, deploy timeout)
- Records all operations for audit

**Tests (minimum 8):**
- Mock adapter: upload + deploy happy path
- Mock adapter: upload invalid archive (rejects)
- Mock adapter: deployment failure scenarios (auth, invalid, timeout)
- Mock adapter: poll deployment returns status transitions
- Real adapter: raises NotImplementedError (OW-010 placeholder)
- Profile loading with env var substitution
- Connection with invalid credentials
- Disconnect cleanup

#### Task 3: Deployment State Machine

**New module:** `apps/cli/oiw/deploy/state_machine.py`

```python
class DeploymentState(Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    TESTED = "TESTED"
    BUILT = "BUILT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    UPLOADED = "UPLOADED"
    DEPLOYED = "DEPLOYED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"

class DeploymentStateMachine:
    def __init__(self, project_path: Path, profile: EnvironmentProfile):
        self.state_file = project_path / ".oiw" / "deployments" / f"{profile.name}.json"
        self.state = self._load_or_init()
    
    def transition(self, event: DeploymentEvent) -> DeploymentState:
        """Validate transition is legal, update state, persist."""
        allowed = self.ALLOWED_TRANSITIONS.get(self.state.current, [])
        if event.target not in allowed:
            raise InvalidTransitionError(self.state.current, event.target)
        self.state.current = event.target
        self.state.history.append(TransitionRecord(
            from_state=self.state.current,
            to_state=event.target,
            timestamp=utcnow(),
            actor=event.actor,
            evidence=event.evidence,
        ))
        self._persist()
        return self.state.current
    
    ALLOWED_TRANSITIONS = {
        DRAFT: [VALIDATED, FAILED],
        VALIDATED: [TESTED, FAILED],
        TESTED: [BUILT, FAILED],
        BUILT: [PROPOSED, FAILED],
        PROPOSED: [APPROVED, FAILED],
        APPROVED: [UPLOADED, FAILED],  # expires after approvalTtlHours
        UPLOADED: [DEPLOYED, FAILED],
        DEPLOYED: [VERIFIED, FAILED],
        VERIFIED: [],
        FAILED: [VALIDATED, PROPOSED],  # retry from last good state
    }
```

**Evidence tracking:** Every state transition records evidence (test results, build digest, deployment ID, approver, etc.). This becomes part of the trajectory outcome.

**Tests (minimum 6):**
- Valid forward transitions through happy path
- Invalid transitions rejected (e.g., DRAFT → DEPLOYED)
- FAILED allows retry from VALIDATED or PROPOSED
- APPROVED expires after TTL
- Evidence recorded for each transition
- State persisted to disk, survives restart

#### Task 4: Drift Detection

**New module:** `apps/cli/oiw/deploy/drift.py`

```python
class DriftDetector:
    def detect_drift(
        self,
        local_build_digest: str,
        tenant_adapter: TenantAdapter,
        package_id: str,
    ) -> DriftReport:
        """Compare local build against tenant state."""
        tenant_version = await tenant_adapter.get_artifact_version(package_id)
        tenant_digest = await tenant_adapter.get_artifact_digest(package_id)
        
        if tenant_digest is None:
            return DriftReport(status="NO_TENANT_ARTIFACT", safe_to_upload=True)
        
        if tenant_digest == local_build_digest:
            return DriftReport(status="IN_SYNC", safe_to_upload=True)
        
        # Digests differ — someone modified the tenant directly
        return DriftReport(
            status="DRIFT_DETECTED",
            safe_to_upload=False,
            local_digest=local_build_digest,
            tenant_digest=tenant_digest,
            tenant_version=tenant_version,
            recommendation="Fetch tenant artifact, review changes, resolve manually.",
        )

# CLI integration
# oiw deploy --profile dev --check-drift
# → DRIFT_DETECTED: tenant has been modified since last export. Upload blocked.
```

**Tests (minimum 4):**
- No tenant artifact → safe to upload
- Digests match → safe to upload
- Digests differ → drift detected, upload blocked
- Drift report includes recommendation and evidence

#### Task 5: GitHub Actions CI/CD Templates

**New directory:** `packages/ci-templates/.github/workflows/`

```yaml
# packages/ci-templates/.github/workflows/oiw-validate.yaml
name: OIW Validate
on: [pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install OIW CLI
        run: pip install oiw-cli
      - name: Validate
        run: oiw validate --strict
      - name: Test
        run: oiw test --all
      - name: Build
        run: oiw build --target sap-cloud-integration-2026-07
      - name: Security scan
        run: oiw security-check
      - name: Upload build artifact
        uses: actions/upload-artifact@v4
        with:
          name: oiw-package
          path: dist/*.zip

# packages/ci-templates/.github/workflows/oiw-deploy.yaml
name: OIW Deploy
on:
  workflow_dispatch:
    inputs:
      profile:
        description: 'Environment profile'
        required: true
        default: 'dev'
      package_id:
        description: 'Package ID to deploy'
        required: true
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ github.event.inputs.profile }}
    steps:
      - uses: actions/checkout@v4
      - name: Install OIW CLI
        run: pip install oiw-cli
      - name: Check drift
        run: oiw deploy --profile ${{ github.event.inputs.profile }} --check-drift
      - name: Build
        run: oiw build --target sap-cloud-integration-2026-07
      - name: Upload to tenant
        run: oiw deploy --profile ${{ github.event.inputs.profile }} --upload
      - name: Deploy
        run: oiw deploy --profile ${{ github.event.inputs.profile }} --execute
        env:
          SAP_CLIENT_SECRET: ${{ secrets.SAP_CLIENT_SECRET }}
      - name: Verify
        run: oiw deploy --profile ${{ github.event.inputs.profile }} --verify
```

**Documentation:** `docs/ci-cd/github-actions.md` — setup guide, required secrets, environment protection.

**Tests (minimum 2):**
- Template YAML validates against GitHub Actions schema
- Required secrets documented, missing secrets fail fast

#### Task 6: Deploy CLI Command + REST Endpoint + MCP Tool

**CLI:**
```bash
oiw deploy --profile dev --package order-to-s4 --check-drift
oiw deploy --profile dev --package order-to-s4 --propose
oiw deploy --profile dev --package order-to-s4 --approve --approver integration-lead
oiw deploy --profile dev --package order-to-s4 --upload
oiw deploy --profile dev --package order-to-s4 --execute
oiw deploy --profile dev --package order-to-s4 --verify
oiw deploy --profile dev --package order-to-s4 --status
```

**REST endpoints** (add to `apps/server-python-prototype/`):
```
POST   /api/v1/projects/{projectId}/deployments:propose
POST   /api/v1/projects/{projectId}/deployments:approve
POST   /api/v1/projects/{projectId}/deployments:execute
POST   /api/v1/projects/{projectId}/deployments:verify
GET    /api/v1/projects/{projectId}/deployments/{deploymentId}
GET    /api/v1/projects/{projectId}/deployments/{deploymentId}/drift
```

**MCP tools** (add to `apps/mcp-server/`):
```
tenant.compare
tenant.deploy_proposal
tenant.deploy_approve
tenant.deploy_execute
tenant.deploy_verify
tenant.get_status
```

**Tests (minimum 6):**
- CLI: propose → approve → upload → execute → verify happy path
- CLI: drift check blocks upload
- REST: all 6 endpoints
- MCP: all 6 tools
- Approval required for execute (no approval → 403)
- Approver must be in profile's approvers list

#### Task 7: Post-Deployment Smoke Test (VERIFIED State)

**What to build:** After deployment, run a smoke test against the tenant to verify the artifact is actually working.

```python
class DeploymentVerifier:
    async def verify(
        self,
        tenant_adapter: TenantAdapter,
        package_id: str,
        smoke_tests: list[SmokeTest],
    ) -> VerificationResult:
        """Run smoke tests against deployed artifact."""
        results = []
        for test in smoke_tests:
            result = await self._run_smoke_test(tenant_adapter, test)
            results.append(result)
            if result.status == "FAILED":
                return VerificationResult(status="FAILED", results=results)
        return VerificationResult(status="VERIFIED", results=results)

# Smoke test definition (in flow.yaml)
spec:
  smokeTests:
    - name: happy-path
      entrypoint: sender-http
      body: fixtures/order.json
      expect:
        status: 201
        bodyContains: "id"
```

**Tests (minimum 3):**
- Smoke test passes → VERIFIED state
- Smoke test fails → FAILED state, deployment rolled back (if supported)
- Verification results recorded in trajectory outcome

---

### Track B: EMG Phase B (Intra-Task Correction)

#### Task 8: Action Decision Graph Builder

**New module:** `apps/cli/oiw/emg/graph_builder.py`

```python
class ActionDecisionGraphBuilder:
    def build(self, trajectory: EngineeringTrajectory) -> ActionDecisionGraph:
        """Convert trajectory to directed, edge-labelled ADG per spec §15.3."""
        G = nx.DiGraph()
        G.graph["query"] = trajectory.spec.query.normalized
        G.graph["reward"] = trajectory.spec.outcome.reward
        G.graph["status"] = trajectory.spec.outcome.status
        
        # Virtual INIT node
        init_id = "INIT"
        G.add_node(init_id, action=InitAction(), observation=None)
        
        prev_node = init_id
        for step in trajectory.spec.steps:
            action_id = self._action_node_id(step.action)
            obs_label = normalize_observation(step.observation)
            
            # Node reuse: if action already exists, reuse it (spec §15.6)
            if action_id not in G:
                G.add_node(action_id, 
                           action=step.action,
                           result_status=step.result.status,
                           provenance=step.action.arguments_digest)
            
            # Edge: observation that preceded this action
            G.add_edge(prev_node, action_id, 
                       observation=obs_label,
                       diagnostic_code=step.observation.diagnostic_code,
                       step_index=step.index)
            
            # Only advance prev_node if observation was informative
            if self._is_informative(step.observation):
                prev_node = action_id
        
        return ActionDecisionGraph(graph=G, trajectory_id=trajectory.metadata.id)
    
    def _action_node_id(self, action: ActionRecord) -> str:
        """Stable ID from normalized tuple."""
        return ":".join(action.normalized)
    
    def _is_informative(self, observation: ObservationRecord) -> bool:
        """Uninformative repeated failures don't advance state (spec §15.5)."""
        return observation.type not in ("repeated-failure", "no-op")
```

**Tests (minimum 5):**
- Build ADG from 3-step trajectory → 4 nodes (INIT + 3 actions)
- Node reuse: same action twice → 1 node, 2 incoming edges
- Edge labels include normalized observation
- Uninformative observations don't advance prev_node
- Graph is deterministic for same trajectory

#### Task 9: Exact Matcher (Stage 1)

**New module:** `apps/cli/oiw/emg/matching/exact.py`

```python
class ExactMatcher:
    """Stage 1: stable tuple equality, same diagnostic codes, same IR version."""
    
    def match(
        self,
        exploration: ActionDecisionGraph,
        expert: ActionDecisionGraph,
    ) -> MatchResult:
        """Find exact node correspondences."""
        correspondence = {}
        
        for exp_node in exploration.graph.nodes:
            for exp_node_data in exploration.graph.nodes[exp_node]:
                # Find expert node with identical normalized action
                for expert_node in expert.graph.nodes:
                    expert_node_data = expert.graph.nodes[expert_node]
                    if self._nodes_match(exp_node_data, expert_node_data):
                        correspondence[exp_node] = expert_node
                        break
        
        return MatchResult(
            stage="exact",
            correspondence=correspondence,
            confidence=len(correspondence) / max(len(exploration.graph.nodes), 1),
            unmatched_explored=set(exploration.graph.nodes) - set(correspondence.keys()),
            unmatched_expert=set(expert.graph.nodes) - set(correspondence.values()),
        )
    
    def _nodes_match(self, a: dict, b: dict) -> bool:
        return (
            a["action"].normalized == b["action"].normalized
            and a.get("ir_version") == b.get("ir_version")
            and a.get("plugin_version") == b.get("plugin_version")
        )
```

**Tests (minimum 4):**
- Identical trajectories → 100% correspondence
- Different actions → no correspondence
- Same action, different IR version → no correspondence
- Confidence score correct

#### Task 10: Rule-Based Matcher (Stage 2)

**New module:** `apps/cli/oiw/emg/matching/rule_based.py`

```python
class RuleBasedMatcher:
    """Stage 2: aliases, diagnostic class grouping, role mapping."""
    
    ALIASES = {
        "receiver-http": "outbound-http-adapter",
        "sender-https": "inbound-https-sender",
        "script-groovy": "groovy-script-step",
    }
    
    DIAGNOSTIC_CLASSES = {
        "OIW-E001": "missing-endpoint",
        "OIW-E002": "inline-secret",
        "OIW-E003": "unbounded-splitter",
        # ... group related codes
    }
    
    ROLE_MAPPING = {
        r"node-[a-f0-9]+": "anonymous-node",
        r"sender-[a-z]+": "sender",
        r"receiver-[a-z]+": "receiver",
    }
    
    def match(
        self,
        exploration: ActionDecisionGraph,
        expert: ActionDecisionGraph,
        prior: MatchResult,
    ) -> MatchResult:
        """Apply rule-based equivalences to unmatched nodes."""
        correspondence = dict(prior.correspondence)
        
        for exp_node in prior.unmatched_explored:
            for expert_node in prior.unmatched_expert:
                if self._rule_equivalent(exp_node, expert_node, exploration, expert):
                    correspondence[exp_node] = expert_node
                    break
        
        return MatchResult(
            stage="rule-based",
            correspondence=correspondence,
            confidence=len(correspondence) / max(len(exploration.graph.nodes), 1),
            unmatched_explored=set(exploration.graph.nodes) - set(correspondence.keys()),
            unmatched_expert=set(expert.graph.nodes) - set(correspondence.values()),
        )
```

**Tests (minimum 4):**
- Alias match: receiver-http ≡ outbound-http-adapter
- Diagnostic class match: OIW-E001 ≡ OIW-E007 (both missing-endpoint)
- Role mapping: node-abc123 → anonymous-node
- No false positives on dissimilar nodes

#### Task 11: Common Subgraph Extractor

**New module:** `apps/cli/oiw/emg/subgraph/common.py`

```python
class CommonSubgraphExtractor:
    """Extract actions and transitions already correct (spec §15.9)."""
    
    def extract(
        self,
        exploration: ActionDecisionGraph,
        expert: ActionDecisionGraph,
        match: MatchResult,
    ) -> CommonSubgraph:
        """Return the subgraph of actions that were already correct."""
        common_nodes = []
        common_edges = []
        
        for exp_node, expert_node in match.correspondence.items():
            # Node is common if both have same action and result
            if (exploration.graph.nodes[exp_node]["result_status"] == "applied"
                and expert.graph.nodes[expert_node]["result_status"] == "applied"):
                common_nodes.append({
                    "action": exploration.graph.nodes[exp_node]["action"],
                    "exploration_id": exp_node,
                    "expert_id": expert_node,
                })
        
        # Common edges: transitions between common nodes with same observation
        for exp_u, exp_v, exp_data in exploration.graph.edges(data=True):
            if exp_u in match.correspondence and exp_v in match.correspondence:
                expert_u = match.correspondence[exp_u]
                expert_v = match.correspondence[exp_v]
                if expert.graph.has_edge(expert_u, expert_v):
                    expert_data = expert.graph.edges[expert_u, expert_v]
                    if exp_data["observation"] == expert_data["observation"]:
                        common_edges.append({
                            "from": exp_u,
                            "to": exp_v,
                            "observation": exp_data["observation"],
                        })
        
        return CommonSubgraph(nodes=common_nodes, edges=common_edges)
```

**Tests (minimum 3):**
- Identical trajectories → entire graph is common
- Exploration has extra failed step → common subgraph excludes it
- Common edges require matching observations

#### Task 12: Graph Edit Path Extractor

**New module:** `apps/cli/oiw/emg/subgraph/edit_path.py`

```python
class GraphEditPathExtractor:
    """Extract INSERT/DELETE/RELABEL operations (spec §15.9)."""
    
    def extract(
        self,
        exploration: ActionDecisionGraph,
        expert: ActionDecisionGraph,
        match: MatchResult,
        common: CommonSubgraph,
    ) -> GraphEditPath:
        """Return operations needed to transform exploration into expert."""
        operations = []
        
        # DELETE: exploration nodes not in correspondence
        for exp_node in match.unmatched_explored:
            operations.append(EditOperation(
                type="DELETE",
                target=exp_node,
                action=exploration.graph.nodes[exp_node]["action"],
                reason="Not present in expert trajectory",
            ))
        
        # INSERT: expert nodes not in correspondence
        for expert_node in match.unmatched_expert:
            operations.append(EditOperation(
                type="INSERT",
                target=expert_node,
                action=expert.graph.nodes[expert_node]["action"],
                reason="Required by expert trajectory",
            ))
        
        # RELABEL: corresponding nodes with different outcomes
        for exp_node, expert_node in match.correspondence.items():
            exp_status = exploration.graph.nodes[exp_node]["result_status"]
            expert_status = expert.graph.nodes[expert_node]["result_status"]
            if exp_status != expert_status:
                operations.append(EditOperation(
                    type="RELABEL",
                    target=exp_node,
                    from_status=exp_status,
                    to_status=expert_status,
                    action=exploration.graph.nodes[exp_node]["action"],
                    reason=f"Outcome differs: {exp_status} → {expert_status}",
                ))
        
        # EDGE CORRECTION: different observation-conditioned transitions
        for exp_node in match.correspondence:
            exp_successors = set(exploration.graph.successors(exp_node))
            expert_successors = set(expert.graph.successors(match.correspondence[exp_node]))
            if exp_successors != expert_successors:
                operations.append(EditOperation(
                    type="EDGE_CORRECTION",
                    target=exp_node,
                    from_successors=exp_successors,
                    to_successors=expert_successors,
                    reason="Different next actions",
                ))
        
        return GraphEditPath(operations=operations)
```

**Tests (minimum 4):**
- DELETE: exploration has extra failed step
- INSERT: expert has additional step not in exploration
- RELABEL: same action, different outcome
- EDGE_CORRECTION: different successors

#### Task 13: Intra-Task Insight Compiler

**New module:** `apps/cli/oiw/emg/insight/compiler.py`

```python
class IntraTaskInsightCompiler:
    """Compile common subgraph + edit path into machine-readable insight."""
    
    def compile(
        self,
        task_id: str,
        exploration: ActionDecisionGraph,
        expert: ActionDecisionGraph,
        common: CommonSubgraph,
        edit_path: GraphEditPath,
    ) -> IntraTaskInsight:
        return IntraTaskInsight(
            task_id=task_id,
            successful_workflow=self._serialize_subgraph(common),
            corrections=[
                CorrectionRule(
                    trigger=self._describe_trigger(op),
                    avoid=[self._describe_avoid(op)],
                    prefer=[self._describe_prefer(op)],
                    confidence=1.0,
                )
                for op in edit_path.operations
            ],
            provenance=InsightProvenance(
                exploration_trajectory_id=exploration.graph.graph["trajectory_id"],
                expert_trajectory_id=expert.graph.graph["trajectory_id"],
                match_stage="rule-based",  # or "exact", "alignment"
                compiler_version="0.1.0",
            ),
        )
    
    def _serialize_subgraph(self, common: CommonSubgraph) -> list[dict]:
        """Machine-readable workflow: sequence of actions with observations."""
        return [
            {"action": n["action"].normalized, "result": "applied"}
            for n in common.nodes
        ]
    
    def _describe_trigger(self, op: EditOperation) -> dict:
        """What observation/action state triggers this correction."""
        if op.type == "DELETE":
            return {"diagnostic": "FAILED", "action": op.action.normalized}
        elif op.type == "INSERT":
            return {"precedes": op.action.normalized}
        # ...
```

**Tests (minimum 3):**
- Compile insight from failed exploration + expert
- Corrections list is non-empty when edit path non-empty
- Provenance includes both trajectory IDs

#### Task 14: Memory Promotion Workflow

**New module:** `apps/cli/oiw/emg/promotion.py`

```python
class MemoryPromotionState(Enum):
    CAPTURED = "CAPTURED"
    REDACTED = "REDACTED"
    OUTCOME_VERIFIED = "OUTCOME_VERIFIED"
    MATCHED = "MATCHED"
    INSIGHT_GENERATED = "INSIGHT_GENERATED"
    REVIEWED = "REVIEWED"
    PROJECT_APPROVED = "PROJECT_APPROVED"
    ORGANIZATION_APPROVED = "ORGANIZATION_APPROVED"
    DEPRECATED = "DEPRECATED"
    REVOKED = "REVOKED"

class MemoryPromotionWorkflow:
    def __init__(self, db: InMemoryInsightStore):
        self.db = db
    
    def record(self, trajectory: EngineeringTrajectory) -> InsightRecord:
        """CAPTURED: raw trajectory recorded."""
        return self.db.insert(InsightRecord(state=CAPTURED, trajectory=trajectory))
    
    def redact(self, insight_id: str) -> InsightRecord:
        """REDACTED: secrets stripped."""
        insight = self.db.get(insight_id)
        insight.trajectory = Redactor().redact_trajectory(insight.trajectory)
        insight.state = REDACTED
        return self.db.update(insight)
    
    def verify_outcome(self, insight_id: str, tests_pass: bool, deploy_success: bool) -> InsightRecord:
        """OUTCOME_VERIFIED: tests + deployment verified."""
        insight = self.db.get(insight_id)
        if not (tests_pass and deploy_success):
            raise VerificationFailedError("Outcome not verified")
        insight.state = OUTCOME_VERIFIED
        return self.db.update(insight)
    
    def match(self, insight_id: str, exploration: ADG, expert: ADG) -> InsightRecord:
        """MATCHED: graph matching completed."""
        # ... run matchers, store result
        insight.state = MATCHED
        return self.db.update(insight)
    
    def generate_insight(self, insight_id: str) -> InsightRecord:
        """INSIGHT_GENERATED: machine-readable correction extracted."""
        # ... compile insight
        insight.state = INSIGHT_GENERATED
        return self.db.update(insight)
    
    def review(self, insight_id: str, reviewer: str) -> InsightRecord:
        """REVIEWED: human reviewed."""
        insight.reviewed_by = reviewer
        insight.state = REVIEWED
        return self.db.update(insight)
    
    def approve_project(self, insight_id: str, approver: str) -> InsightRecord:
        """PROJECT_APPROVED: available within project."""
        insight.state = PROJECT_APPROVED
        return self.db.update(insight)
    
    def deprecate(self, insight_id: str, reason: str) -> InsightRecord:
        """DEPRECATED: adapter/compiler changed."""
        insight.state = DEPRECATED
        insight.deprecation_reason = reason
        return self.db.update(insight)
    
    def revoke(self, insight_id: str, reason: str) -> InsightRecord:
        """REVOKED: caused incident; excluded from retrieval."""
        insight.state = REVOKED
        insight.revocation_reason = reason
        return self.db.update(insight)
```

**CLI commands:**
```bash
oiw memory list --project my-project
oiw memory promote --insight traj-abc123 --to OUTCOME_VERIFIED --tests-pass --deploy-success
oiw memory promote --insight traj-abc123 --to REVIEWED --reviewer alice
oiw memory promote --insight traj-abc123 --to PROJECT_APPROVED --approver bob
oiw memory deprecate --insight traj-abc123 --reason "adapter changed"
oiw memory revoke --insight traj-abc123 --reason "caused incident INC-123"
```

**Tests (minimum 8):**
- Full promotion path: CAPTURED → PROJECT_APPROVED
- Invalid transitions rejected (e.g., CAPTURED → APPROVED)
- Deprecation prevents retrieval
- Revocation prevents retrieval + records reason
- Redaction strips secrets
- Verification requires tests + deploy success
- Review requires reviewer identity
- Listing filters by state and project

#### Task 15: Reward Vector Extension

**Modify:** `apps/cli/oiw/agent/orchestrator.py` `_compute_reward()`

```python
def _compute_reward(
    result: ExecutionResult,
    validation: ValidationResult,
    deployment: DeploymentResult | None = None,
    runtime_stability: float | None = None,
) -> RewardVector:
    return RewardVector(
        # Existing dimensions
        structural_validity=1.0 if validation.passed else 0.0,
        unit_tests=self._test_pass_rate(validation),
        security_policy=1.0 if not validation.has_security_errors else 0.0,
        completion=1.0 if result.status == "COMPLETED" else 0.0,
        corrections_needed=1.0 - (result.corrections / max(result.total_steps, 1)),
        
        # New Phase 4 dimensions
        deployment_success=(
            1.0 if deployment and deployment.state == VERIFIED
            else 0.5 if deployment and deployment.state == DEPLOYED
            else 0.0
        ),
        runtime_stability=runtime_stability or 0.0,  # from post-deploy logs
        
        # Hard gates (spec §15.8)
        hard_gates={
            "no_secret_leakage": not self._has_secret_leakage(validation),
            "no_unauthorized_deployment": not self._has_unauthorized_deploy(deployment),
            "no_critical_security": not validation.has_critical_security,
            "no_corrupt_artifact": not validation.has_corrupt_artifact,
        },
    )
```

**Tests (minimum 4):**
- Deployment verified → deployment_success = 1.0
- Deployment deployed but not verified → deployment_success = 0.5
- No deployment → deployment_success = 0.0
- Hard gate failure prevents promotion

---

### Track C: Cleanup

#### Task 16: OW-029 — Full SPA Decomposition

**Extract from `apps/web/src/App.tsx`:**

```
apps/web/src/components/
├── canvas/
│   ├── FlowCanvas.tsx              # React Flow wrapper
│   ├── nodes/
│   │   ├── SenderNode.tsx
│   │   ├── ReceiverNode.tsx
│   │   ├── ContentModifierNode.tsx
│   │   ├── ScriptNode.tsx
│   │   ├── MappingNode.tsx
│   │   ├── RouterNode.tsx
│   │   └── SubprocessNode.tsx
│   ├── edges/
│   │   ├── MessageFlowEdge.tsx
│   │   └── ConditionalEdge.tsx
│   └── panels/
│       ├── PalettePanel.tsx
│       ├── PropertiesPanel.tsx
│       ├── AdapterConfigPanel.tsx
│       └── ValidationPanel.tsx
├── editors/
│   ├── GroovyEditor.tsx            # Monaco + Groovy LSP
│   ├── XsltEditor.tsx
│   ├── JsonSchemaEditor.tsx
│   └── YamlEditor.tsx
├── llm/                            # Already exists from WP-04
│   ├── CoPilotPanel.tsx
│   ├── PatchPreviewDialog.tsx
│   ├── PlanApprovalDialog.tsx
│   └── TrajectoryIndicator.tsx
├── git/
│   ├── CommitDialog.tsx
│   ├── BranchSelector.tsx
│   ├── SemanticDiffViewer.tsx      # Already exists
│   ├── PullRequestPanel.tsx
│   └── HistoryTimeline.tsx
├── testing/
│   ├── TestRunnerPanel.tsx
│   ├── TraceViewer.tsx
│   ├── MockConfigEditor.tsx
│   └── AssertionBuilder.tsx
├── deploy/                         # NEW for WP-05
│   ├── DeployPanel.tsx
│   ├── DriftReportDialog.tsx
│   ├── ApprovalDialog.tsx
│   └── DeploymentStatusCard.tsx
└── shared/
    ├── ProjectExplorer.tsx
    ├── ValidationBadge.tsx
    ├── FidelityIndicator.tsx
    └── SimulationConsole.tsx
```

**App.tsx after decomposition:** ~200 lines, imports components, manages top-level state.

**Tests (minimum 5):**
- All extracted components render
- App.tsx wires them correctly
- Existing Playwright E2E tests still pass
- New deploy panel components render
- No regressions in existing UI behavior

#### Task 17: OW-023/024 — Eval Harness Improvements

**OW-023:** Wire LLM planner into bench-002 and bench-003.

```python
# tests/agent_eval/runner.py
async def run_benchmark_with_llm(benchmark: Benchmark, gateway: ModelGatewayClient) -> BenchmarkResult:
    """Run benchmark with real LLM planner (requires OIW_MODEL_GATEWAY_KEY)."""
    # ... use real gateway, not mock
```

**OW-024:** Replace coarse metric parsers with structured readers.

```python
# tests/agent_eval/metrics.py
def count_policy_violations_structured(validation: ValidationResult) -> int:
    """Count ERROR-level diagnostics from structured output, not text parsing."""
    return len([d for d in validation.diagnostics if d.severity == "ERROR"])

def compute_test_pass_rate_structured(test_results: list[TestResult]) -> float:
    """Compute from TestResult objects, not text parsing."""
    if not test_results:
        return 0.0
    return sum(1 for t in test_results if t.passed) / len(test_results)
```

**Tests (minimum 3):**
- bench-002 with LLM → PASS (structural >= 0.9)
- bench-003 with LLM → PASS
- Structured metric parsers match text parsers on known inputs

---

## 4. Sequencing & Dependencies

```
Track A (Tenant Deployment):
  Task 1 (Profiles) ─────────────────────────────────┐
                                                     │
  Task 2 (Adapter + Mock) ── depends on Task 1 ─────┤
                                                     │
  Task 3 (State Machine) ── depends on Task 2 ──────┤
                                                     │
  Task 4 (Drift Detection) ─ depends on Task 2 ─────┤
                                                     │
  Task 5 (CI/CD Templates) ── independent ───────────┤
                                                     │
  Task 6 (CLI/REST/MCP) ──── depends on 2,3,4 ──────┤
                                                     │
  Task 7 (Smoke Test) ────── depends on Task 6 ──────┤
                                                     │
Track B (EMG Phase B):                               │
  Task 8 (ADG Builder) ───── independent ────────────┤
                                                     │
  Task 9 (Exact Matcher) ─── depends on Task 8 ──────┤
                                                     │
  Task 10 (Rule Matcher) ─── depends on Task 9 ──────┤
                                                     │
  Task 11 (Common Subgraph) ─ depends on Task 10 ────┤
                                                     │
  Task 12 (Edit Path) ────── depends on Task 11 ─────┤
                                                     │
  Task 13 (Insight Compiler)  depends on Task 12 ────┤
                                                     │
  Task 14 (Promotion) ────── depends on Task 13 ─────┤
                                                     │
  Task 15 (Reward Vector) ── depends on Task 7 ──────┤ (needs deployment outcomes)
                                                     │
Track C (Cleanup):                                   │
  Task 16 (SPA Decomp) ───── independent ────────────┤
                                                     │
  Task 17 (Eval Harness) ──── independent ────────────┘
```

**Suggested order (3 weeks):**

| Week | Tasks | Milestone |
|------|-------|-----------|
| 1 | Tasks 1, 2, 3, 4, 8 | Profiles load, mock adapter works, state machine transitions, drift detected, ADGs built from trajectories |
| 2 | Tasks 5, 6, 7, 9, 10, 11, 12 | CI/CD templates, deploy CLI works end-to-end, exact + rule matching work, common subgraphs extracted, edit paths computed |
| 3 | Tasks 13, 14, 15, 16, 17 | Insights compiled, promotion workflow works, reward vector includes deployment dimensions, SPA decomposed, eval harness improved |

---

## 5. Acceptance Criteria (Work Package Level)

This work package is complete when **all** of the following are true:

- [ ] `oiw deploy --profile dev --package order-to-s4 --propose` creates a PROPOSED deployment record.
- [ ] `oiw deploy --profile dev --approve --approver integration-lead` transitions to APPROVED.
- [ ] `oiw deploy --profile dev --upload` uploads to mock tenant (or real tenant if OW-010 resolved).
- [ ] `oiw deploy --profile dev --execute` deploys and polls for DEPLOYED state.
- [ ] `oiw deploy --profile dev --verify` runs smoke tests and transitions to VERIFIED.
- [ ] Drift detection blocks upload when tenant has been modified externally.
- [ ] Deployment state machine enforces approval gates (no execute without approve).
- [ ] GitHub Actions templates exist and validate.
- [ ] Every trajectory produces an Action Decision Graph.
- [ ] Failed trajectories produce machine-readable correction paths against expert trajectories.
- [ ] Common subgraphs are extracted correctly.
- [ ] Graph edit paths include INSERT/DELETE/RELABEL/EDGE_CORRECTION operations.
- [ ] Intra-task insights are compiled and persisted.
- [ ] Memory promotion workflow enforces state transitions.
- [ ] Reward vector includes `deployment_success` and `runtime_stability` dimensions.
- [ ] Hard gates prevent promotion on secret leakage, unauthorized deployment, critical security, corrupt artifact.
- [ ] SPA is fully decomposed (App.tsx < 300 lines).
- [ ] Eval harness includes bench-002/003 with LLM planner (nightly).
- [ ] All new code has tests. Total test count increases by ≥ 50.
- [ ] CI is green with all 12 existing checks + 1 new `deploy-e2e` check.
- [ ] DEVELOPMENT_LOG.md updated with new deviations and open work items.

---

## 6. Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| SAP CI tenant access unavailable (OW-010) | Phase 4 can't be tested against real tenant | Mock adapter for all testing; real adapter stub with NotImplementedError; document as known gap |
| EMG graph matching too slow on large trajectories | Promotion workflow blocks | Limit trajectory size (max 50 steps); async workers; cache match results |
| Drift detection false positives | Blocks legitimate uploads | `--force-upload` flag with explicit acknowledgment; log override for audit |
| Smoke tests fail in tenant | VERIFIED state unreachable | Configurable smoke test subset; allow VERIFIED skip with warning |
| SPA decomposition breaks existing UI | Playwright E2E tests fail | Incremental extraction; run E2E after each component; revert on failure |
| Reward vector dimensions not comparable | EMG retrieval ranks incorrectly | Normalize all dimensions to [0, 1]; version the reward schema; log raw + normalized |
| Memory promotion state machine bugs | Insights stuck in wrong state | Comprehensive state transition tests; audit log for all state changes |

---

## 7. Out of Scope (Explicit)

These are **not** part of this work package:

- Real SAP CI tenant adapter implementation (OW-010 — requires tenant access)
- EMG Phase C (cross-task transfer) — requires intra-task memory from this WP first
- EMG Phase D (optimal-transport alignment) — requires Phase C first
- EMG Phase E (continuous governance) — requires Phase D first
- Kotlin/Spring Boot migration (OW-001, OW-002) — separate ADR decision
- JVM runtime worker with seccomp (OW-003) — separate work package
- Additional step plugins (Phase 6) — separate work package
- WebSocket real-time trace streaming (OW-018) — low priority

---

## 8. Definition of Done (Per PR)

Every PR within this work package must satisfy the spec §33 definition of done:

- [ ] Tests added or updated.
- [ ] Threat impact considered.
- [ ] No secrets in fixtures.
- [ ] Public API documented.
- [ ] Schema changes versioned.
- [ ] Compatibility diagnostics updated.
- [ ] UI and CLI remain consistent.
- [ ] SBOM and scans pass.
- [ ] ADR added for significant architectural change.
- [ ] `Human-Approver` trailer filled (CI enforces).
- [ ] DEVELOPMENT_LOG.md updated.

---

## 9. Strategic Outcome

After WP-05, the project will have:

1. **A working deployment pipeline** — consultants can develop locally, test locally, and deploy to real tenants with approval gates and drift detection.
2. **A mechanical graph-matching core** — every trajectory produces an Action Decision Graph, and failed trajectories produce machine-readable correction paths.
3. **A memory promotion workflow** — insights flow from CAPTURED to PROJECT_APPROVED through explicit gates.
4. **A complete reward vector** — deployment outcomes feed into the EMG, enabling future phases to learn from real production results.
5. **A decomposed SPA** — the UI is maintainable and ready for Phase 5 additions (EMG insight cards, trajectory viewer, pattern browser).

This sets up WP-06 (EMG Phase C: Cross-Task Transfer), which is where the "TurboVLA-style mechanics" fully kick in — replacing LLM planning with deterministic graph retrieval for known patterns, and using the LLM only for novel requirements and bounded correction.

---

*End of Work Package WP-05*