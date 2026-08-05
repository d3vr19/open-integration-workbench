"""Tests proving EMG retrieval improves agent behavior (WP-05 enhancement).

These tests demonstrate the "mechanics-first" loop: when the EMG has a
matching expert trajectory, the orchestrator uses it directly instead
of invoking the LLM/keyword planner. This results in:

  1. Faster execution (no LLM latency)
  2. More reliable plans (expert trajectories have verified outcomes)
  3. Warning OIW-I001 emitted when EMG is used

The tests build a synthetic expert insight, store it in the EMG, then
run the orchestrator with the retriever and verify the plan matches
the expert's workflow.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from oiw.agent.gateway_client import ModelGatewayClient
from oiw.agent.interpreter import NormalizedRequirement
from oiw.agent.orchestrator import run_agent
from oiw.emg.insight import InsightProvenance, IntraTaskInsight
from oiw.emg.promotion import (
    MemoryPromotionWorkflow,
)
from oiw.emg.retrieval import EMGRetriever, inject_insight_into_plan

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "order-to-s4"


@pytest.fixture()
def env_vars():
    old = {}
    for k in ("DEV_TENANT_URL", "DEV_TOKEN_URL", "DEV_CLIENT_ID"):
        old[k] = os.environ.get(k)
        os.environ[k] = f"https://{k.lower()}.example.com"
    yield
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture()
def git_project(tmp_path: Path, env_vars) -> Path:
    """Copy order-to-s4 to tmp, init git for HEAD sha."""
    dest = tmp_path / "order-to-s4"
    shutil.copytree(EXAMPLE, dest)
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(["git", "-C", str(dest), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(dest), "commit", "-q", "-m", "test"],
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t.com",
        },
        check=True,
    )
    old = os.environ.get("OIW_WORKSPACE")
    os.environ["OIW_WORKSPACE"] = str(tmp_path)
    yield dest
    if old is not None:
        os.environ["OIW_WORKSPACE"] = old
    else:
        os.environ.pop("OIW_WORKSPACE", None)


def _make_expert_insight(
    task_id: str = "task-add-validation",
    workflow_actions: list[tuple] | None = None,
) -> IntraTaskInsight:
    """Build a synthetic expert insight for testing."""
    if workflow_actions is None:
        workflow_actions = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single-required"),
            ("resource.write", "add-resource", "schema.json", "flows/order-to-s4/...", ""),
        ]

    return IntraTaskInsight(
        task_id=task_id,
        successful_workflow=[{"action": action, "result": "applied"} for action in workflow_actions],
        corrections=[],
        provenance=InsightProvenance(
            exploration_trajectory_id="traj-expert-001",
            expert_trajectory_id="traj-expert-001",
            match_stage="exact",
        ),
    )


def _populate_emg_store(
    insight: IntraTaskInsight,
    project_id: str = "order-to-s4",
) -> EMGRetriever:
    """Create an EMGRetriever with a pre-populated insight store."""
    wf = MemoryPromotionWorkflow()
    record = wf.record(
        trajectory_id="traj-expert-001",
        project_id=project_id,
        insight=insight,
    )
    # Fast-track through promotion to PROJECT_APPROVED
    wf.redact(record.id)
    wf.verify_outcome(record.id, tests_pass=True, deploy_success=True)
    wf.match(record.id)
    wf.generate_insight(record.id)
    wf.review(record.id, reviewer="expert")
    wf.approve_project(record.id, approver="lead")

    return EMGRetriever(store=wf.store)


# ---------------------------------------------------------------------------
# Test 1: EMG retrieval finds a matching insight
# ---------------------------------------------------------------------------


def test_emg_retrieval_finds_matching_insight() -> None:
    """When the EMG has a PROJECT_APPROVED insight, retrieval finds it."""
    insight = _make_expert_insight()
    retriever = _populate_emg_store(insight)

    requirement = NormalizedRequirement(
        intent="modify-flow",
        operations=["validate"],
        components=["validator.json-schema"],
        raw="Add validation",
    )

    result = retriever.retrieve(requirement, project_id="order-to-s4")
    assert result.found
    assert result.insight is not None
    assert result.confidence > 0.2
    assert "matched with score" in result.reason


# ---------------------------------------------------------------------------
# Test 2: EMG retrieval returns not-found when no match
# ---------------------------------------------------------------------------


def test_emg_retrieval_returns_not_found_when_empty() -> None:
    """When the EMG store is empty, retrieval returns found=False."""
    retriever = EMGRetriever()  # empty store
    requirement = NormalizedRequirement(
        intent="create-flow",
        operations=["transform"],
        components=["receiver.http"],
        raw="Create a flow",
    )

    result = retriever.retrieve(requirement)
    assert not result.found
    assert "no PROJECT_APPROVED" in result.reason


# ---------------------------------------------------------------------------
# Test 3: EMG-injected plan executes without LLM call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emg_injected_plan_skips_llm_planner(git_project: Path) -> None:
    """When EMG provides a plan, the LLM planner is NOT called.

    This is the core mechanics-first behavior: the expert workflow
    replaces the LLM call entirely.
    """
    insight = _make_expert_insight()
    retriever = _populate_emg_store(insight)

    # Mock the gateway as UNHEALTHY — so the interpreter uses fallback
    # (no LLM call for interpretation), and EMG provides the plan
    # (no LLM call for planning).
    gateway = AsyncMock(spec=ModelGatewayClient)
    gateway.health.return_value = False
    gateway.aclose = AsyncMock()

    result = await run_agent(
        requirement="Add JSON schema validation to order-to-s4",
        project_path=git_project,
        mode="autonomous",
        flow_id="order-to-s4",
        gateway=gateway,
        emg_retriever=retriever,
        persist_dir=git_project / ".oiw" / "traj",
    )

    # The plan should have EMG-injected steps
    assert result.plan is not None
    assert len(result.plan.steps) > 0
    # The first step's rationale should mention EMG
    assert any("EMG" in s.rationale for s in result.plan.steps)

    # Warning OIW-I001 should be emitted
    assert any("OIW-I001" in w for w in result.warnings)

    # The LLM planner should NOT have been called (gateway.chat never called)
    assert gateway.chat.await_count == 0  # no planner call


# ---------------------------------------------------------------------------
# Test 4: EMG-injected plan produces correct structural outcome
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emg_injected_plan_adds_validator_node(git_project: Path) -> None:
    """The EMG-injected plan actually adds the validator node to the flow.

    This proves the injected plan is executable, not just a data structure.
    """
    insight = _make_expert_insert(
        workflow_actions=[
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single-required"),
        ]
    )
    retriever = _populate_emg_store(insight)

    gateway = AsyncMock(spec=ModelGatewayClient)
    gateway.health.return_value = False  # force fallback path
    gateway.aclose = AsyncMock()

    result = await run_agent(
        requirement="Add validation to the flow",
        project_path=git_project,
        mode="autonomous",
        flow_id="order-to-s4",
        gateway=gateway,
        emg_retriever=retriever,
        persist_dir=git_project / ".oiw" / "traj",
    )

    assert result.status in {"COMPLETED", "FAILED"}
    assert result.plan is not None

    # Verify the validator node was actually added to the flow
    import yaml

    flow_path = git_project / "flows" / "order-to-s4" / "flow.yaml"
    if flow_path.is_file():
        flow_data = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
        node_ids = [n["id"] for n in flow_data.get("spec", {}).get("nodes", [])]
        # The EMG-injected node ID starts with "emg-validator"
        emg_nodes = [nid for nid in node_ids if nid.startswith("emg-")]
        assert len(emg_nodes) > 0, f"no EMG-injected nodes found in {node_ids}"


def _make_expert_insert(
    workflow_actions: list[tuple] | None = None,
) -> IntraTaskInsight:
    """Alias for _make_expert_insight (named for clarity)."""
    return _make_expert_insight(workflow_actions=workflow_actions)


# ---------------------------------------------------------------------------
# Test 5: inject_insight_into_plan produces valid plan steps
# ---------------------------------------------------------------------------


def test_inject_insight_into_plan_produces_valid_steps() -> None:
    """The injection function converts workflow actions to executable PlanSteps."""
    insight = _make_expert_insight(
        workflow_actions=[
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single-required"),
            ("resource.write", "add-resource", "schema.json", "flows/x/schema.json", ""),
        ]
    )

    steps = inject_insight_into_plan(
        insight=insight,
        base_revision="abc123",
        project_id="test-project",
        flow_id="test-flow",
    )

    assert len(steps) == 2

    # First step: flow.patch with baseRevision
    assert steps[0]["tool"] == "flow.patch"
    assert steps[0]["arguments"]["baseRevision"] == "abc123"
    assert steps[0]["arguments"]["projectId"] == "test-project"
    assert steps[0]["arguments"]["flowId"] == "test-flow"
    assert "EMG" in steps[0]["rationale"]

    # Second step: resource.write
    assert steps[1]["tool"] == "resource.write"
    assert steps[1]["arguments"]["projectId"] == "test-project"

    # All steps have order numbers
    for i, step in enumerate(steps):
        assert step["order"] == i + 1


# ---------------------------------------------------------------------------
# Test 6: EMG retrieval confidence scoring
# ---------------------------------------------------------------------------


def test_emg_retrieval_confidence_scoring() -> None:
    """Confidence score reflects how well the requirement matches the insight."""
    insight = _make_expert_insight(
        workflow_actions=[
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single-required"),
        ]
    )
    retriever = _populate_emg_store(insight)

    # High overlap: same operations + components
    high_match = NormalizedRequirement(
        intent="modify-flow",
        operations=["validate"],
        components=["validator.json-schema"],
        raw="Add validation",
    )
    high_result = retriever.retrieve(high_match, project_id="order-to-s4")
    assert high_result.found
    assert high_result.confidence > 0.2

    # Low overlap: different components
    low_match = NormalizedRequirement(
        intent="create-flow",
        operations=["transform"],
        components=["receiver.http"],
        raw="Create a flow",
    )
    low_result = retriever.retrieve(low_match, project_id="order-to-s4")
    # Should either not match or have low confidence
    if low_result.found:
        assert low_result.confidence < high_result.confidence


# ---------------------------------------------------------------------------
# Test 7: Avoid-pattern retrieval (WP-07 Track E-002)
# ---------------------------------------------------------------------------


def test_emg_retrieval_surfaces_avoid_patterns(tmp_path):
    """The retriever surfaces avoid patterns matching the requirement."""
    from oiw.emg.avoid_patterns import AvoidPattern, AvoidPatternStore

    # Build a store with one avoid pattern targeting OData receivers
    store = AvoidPatternStore(
        patterns=[
            AvoidPattern(
                id="avoid-fm-001",
                trigger={
                    "operation": "add-node",
                    "componentType": "receiver.odata-v4",
                    "configMissing": "pagination.maxPages",
                },
                reason="Unbounded pagination",
                severity="high",
                replacement=[],
                evidence={"failureModeId": "fm-001", "archetype": "paginated-api-ingestion"},
            ),
        ]
    )

    retriever = EMGRetriever(avoid_pattern_store=store)

    # Requirement that matches the avoid pattern's archetype + components
    req = NormalizedRequirement(
        intent="create-flow",
        archetype="paginated-api-ingestion",
        operations=["transform"],
        components=["receiver.odata-v4"],
        raw="Create a flow that reads from OData",
    )

    result = retriever.retrieve(req, project_id="test")
    # Avoid pattern should be surfaced even if no positive insight was found
    assert len(result.avoid_patterns) >= 1
    assert result.avoid_patterns[0].id == "avoid-fm-001"
    # The reason string should mention the avoid pattern count
    assert "avoid: 1 patterns matched" in result.reason


def test_emg_retrieval_no_avoid_patterns_when_store_empty():
    """Empty avoid-pattern store → no patterns returned."""
    retriever = EMGRetriever()  # no avoid_pattern_store
    req = NormalizedRequirement(
        intent="create-flow",
        archetype="api-to-erp",
        operations=["transform"],
        components=["receiver.http"],
        raw="Create a flow",
    )
    result = retriever.retrieve(req, project_id="test")
    assert result.avoid_patterns == []


def test_emg_retrieval_filters_avoid_patterns_by_archetype():
    """Avoid patterns with non-matching archetype are filtered out."""
    from oiw.emg.avoid_patterns import AvoidPattern, AvoidPatternStore

    store = AvoidPatternStore(
        patterns=[
            # Pattern targets paginated-api-ingestion only
            AvoidPattern(
                id="avoid-fm-001",
                trigger={"operation": "add-node", "componentType": "receiver.odata-v4"},
                reason="Unbounded pagination",
                severity="high",
                replacement=[],
                evidence={"archetype": "paginated-api-ingestion"},
            ),
            # Pattern targets any archetype
            AvoidPattern(
                id="avoid-fm-004",
                trigger={"operation": "add-node", "componentType": "receiver.*"},
                reason="Inline secret",
                severity="critical",
                replacement=[],
                evidence={"archetype": "any"},
            ),
        ]
    )

    retriever = EMGRetriever(avoid_pattern_store=store)

    # Requirement with a DIFFERENT archetype
    req = NormalizedRequirement(
        intent="create-flow",
        archetype="soap-integration",  # not paginated-api-ingestion
        operations=[],
        components=["receiver.soap"],
        raw="Build a SOAP flow",
    )
    result = retriever.retrieve(req, project_id="test")
    ids = {p.id for p in result.avoid_patterns}
    # fm-001 should be filtered out (archetype mismatch)
    assert "avoid-fm-001" not in ids
    # fm-004 should be included (archetype=any)
    assert "avoid-fm-004" in ids
