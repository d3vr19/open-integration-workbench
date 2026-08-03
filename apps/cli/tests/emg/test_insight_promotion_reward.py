"""Tests for insight compiler + promotion workflow + reward vector (WP-05 Tasks 13-15).

Covers:
  - Insight compiler: compile from failed exploration + expert, non-empty corrections, provenance
  - Promotion workflow: full path, invalid transitions, deprecation, revocation, redaction,
    verification, review, listing
  - Reward vector: deployment verified/deployed/none, hard gate failure
"""

from __future__ import annotations

import pytest

from oiw.agent.trajectory import (
    ActionRecord,
    EngineeringTrajectory,
    ObservationRecord,
    ResultRecord,
    TrajectoryMetadata,
    TrajectorySpec,
    TrajectoryStep,
)
from oiw.emg.graph_builder import ActionDecisionGraphBuilder
from oiw.emg.insight import IntraTaskInsightCompiler
from oiw.emg.matching import ExactMatcher
from oiw.emg.promotion import (
    MemoryPromotionState,
    MemoryPromotionWorkflow,
    PromotionError,
)
from oiw.emg.reward import RewardVector, compute_reward
from oiw.emg.subgraph import CommonSubgraphExtractor, GraphEditPathExtractor


def _make_adg(
    steps_data: list[tuple[str, str, str, str, str, str]],
    trajectory_id: str = "traj-test",
):
    steps = []
    for i, (tool, op, comp, target, param, result) in enumerate(steps_data):
        steps.append(
            TrajectoryStep(
                index=i,
                observation=ObservationRecord(type="pre-action", fingerprint=f"fp{i}", summary={}),
                action=ActionRecord(
                    type=tool,
                    normalized=(tool, op, comp, target, param),
                    argumentsDigest=f"digest{i}",
                ),
                result=ResultRecord(status=result, summary="ok"),
            )
        )
    trajectory = EngineeringTrajectory(
        metadata=TrajectoryMetadata(
            id=trajectory_id, projectId="test", taskId="task", baseRevision="abc", startedAt=1000.0
        ),
        spec=TrajectorySpec(steps=steps),
    )
    return ActionDecisionGraphBuilder().build(trajectory)


# ---------------------------------------------------------------------------
# Task 13: IntraTaskInsightCompiler
# ---------------------------------------------------------------------------


class TestInsightCompiler:
    def test_compile_insight_from_failed_exploration(self) -> None:
        """Compile insight from a failed exploration + expert."""
        exp_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "failed"),
        ]
        expert_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
        ]
        exploration = _make_adg(exp_steps, "exp-123")
        expert = _make_adg(expert_steps, "expert-456")

        match = ExactMatcher().match(exploration, expert)
        common = CommonSubgraphExtractor().extract(exploration, expert, match)
        edit_path = GraphEditPathExtractor().extract(exploration, expert, match, common)

        insight = IntraTaskInsightCompiler().compile(
            task_id="task-001",
            exploration=exploration,
            expert=expert,
            common=common,
            edit_path=edit_path,
        )

        assert insight.task_id == "task-001"
        # The exploration failed, so common subgraph is empty
        assert len(insight.successful_workflow) == 0
        # There should be a RELABEL correction (failed → applied)
        assert len(insight.corrections) >= 1

    def test_corrections_non_empty_when_edit_path_non_empty(self) -> None:
        """Corrections list is non-empty when edit path has operations."""
        exp_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
            ("flow.patch", "addNode", "log.message", "add-log", "single", "failed"),  # extra, DELETE
        ]
        expert_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
        ]
        exploration = _make_adg(exp_steps, "exp")
        expert = _make_adg(expert_steps, "expert")

        match = ExactMatcher().match(exploration, expert)
        common = CommonSubgraphExtractor().extract(exploration, expert, match)
        edit_path = GraphEditPathExtractor().extract(exploration, expert, match, common)

        insight = IntraTaskInsightCompiler().compile(
            task_id="task-002", exploration=exploration, expert=expert, common=common, edit_path=edit_path
        )

        assert len(insight.corrections) >= 1
        # At least one DELETE correction
        delete_corrections = [c for c in insight.corrections if c.avoid]
        assert len(delete_corrections) >= 1

    def test_provenance_includes_both_trajectory_ids(self) -> None:
        """Provenance includes both exploration + expert trajectory IDs."""
        exploration = _make_adg(
            [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")],
            "exp-abc",
        )
        expert = _make_adg(
            [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")],
            "expert-xyz",
        )

        match = ExactMatcher().match(exploration, expert)
        common = CommonSubgraphExtractor().extract(exploration, expert, match)
        edit_path = GraphEditPathExtractor().extract(exploration, expert, match, common)

        insight = IntraTaskInsightCompiler().compile(
            task_id="task-003", exploration=exploration, expert=expert, common=common, edit_path=edit_path
        )

        assert insight.provenance is not None
        assert insight.provenance.exploration_trajectory_id == "exp-abc"
        assert insight.provenance.expert_trajectory_id == "expert-xyz"
        assert insight.provenance.match_stage == "rule-based"


# ---------------------------------------------------------------------------
# Task 14: MemoryPromotionWorkflow
# ---------------------------------------------------------------------------


class TestMemoryPromotion:
    def test_full_promotion_path(self) -> None:
        """CAPTURED → REDACTED → OUTCOME_VERIFIED → MATCHED →
        INSIGHT_GENERATED → REVIEWED → PROJECT_APPROVED."""
        wf = MemoryPromotionWorkflow()
        record = wf.record(trajectory_id="traj-1", project_id="proj-1")
        assert record.state == MemoryPromotionState.CAPTURED

        record = wf.redact(record.id)
        assert record.state == MemoryPromotionState.REDACTED

        record = wf.verify_outcome(record.id, tests_pass=True, deploy_success=True)
        assert record.state == MemoryPromotionState.OUTCOME_VERIFIED

        record = wf.match(record.id)
        assert record.state == MemoryPromotionState.MATCHED

        record = wf.generate_insight(record.id)
        assert record.state == MemoryPromotionState.INSIGHT_GENERATED

        record = wf.review(record.id, reviewer="alice")
        assert record.state == MemoryPromotionState.REVIEWED
        assert record.reviewed_by == "alice"

        record = wf.approve_project(record.id, approver="bob")
        assert record.state == MemoryPromotionState.PROJECT_APPROVED
        assert record.approved_by == "bob"

    def test_invalid_transition_rejected(self) -> None:
        """CAPTURED → PROJECT_APPROVED is illegal (skips gates)."""
        wf = MemoryPromotionWorkflow()
        record = wf.record(trajectory_id="traj-1", project_id="proj-1")
        with pytest.raises(PromotionError, match="invalid promotion transition"):
            wf.approve_project(record.id, approver="bob")

    def test_deprecation_prevents_retrieval(self) -> None:
        """DEPRECATED insights are not retrievable."""
        wf = MemoryPromotionWorkflow()
        record = wf.record(trajectory_id="traj-1", project_id="proj-1")
        wf.deprecate(record.id, reason="adapter changed")
        assert not wf.is_retrievable(record.id)

    def test_revocation_prevents_retrieval(self) -> None:
        """REVOKED insights are not retrievable + record reason."""
        wf = MemoryPromotionWorkflow()
        record = wf.record(trajectory_id="traj-1", project_id="proj-1")
        wf.revoke(record.id, reason="caused incident INC-123")
        assert not wf.is_retrievable(record.id)
        updated = wf.store.get(record.id)
        assert updated.revocation_reason == "caused incident INC-123"

    def test_verification_requires_tests_and_deploy(self) -> None:
        """verify_outcome fails if tests or deploy didn't succeed."""
        wf = MemoryPromotionWorkflow()
        record = wf.record(trajectory_id="traj-1", project_id="proj-1")
        wf.redact(record.id)
        with pytest.raises(PromotionError, match="verification failed"):
            wf.verify_outcome(record.id, tests_pass=False, deploy_success=True)
        with pytest.raises(PromotionError, match="verification failed"):
            wf.verify_outcome(record.id, tests_pass=True, deploy_success=False)

    def test_review_requires_reviewer(self) -> None:
        """review() requires a non-empty reviewer identity."""
        wf = MemoryPromotionWorkflow()
        record = wf.record(trajectory_id="traj-1", project_id="proj-1")
        wf.redact(record.id)
        wf.verify_outcome(record.id, tests_pass=True, deploy_success=True)
        wf.match(record.id)
        wf.generate_insight(record.id)
        with pytest.raises(PromotionError, match="reviewer identity is required"):
            wf.review(record.id, reviewer="")

    def test_listing_filters_by_state_and_project(self) -> None:
        """list() filters by project_id and state."""
        wf = MemoryPromotionWorkflow()
        wf.record(trajectory_id="t1", project_id="proj-a")
        wf.record(trajectory_id="t2", project_id="proj-b")
        r3 = wf.record(trajectory_id="t3", project_id="proj-a")
        wf.redact(r3.id)

        # Filter by project
        proj_a = wf.store.list(project_id="proj-a")
        assert len(proj_a) == 2

        # Filter by state
        redacted = wf.store.list(state=MemoryPromotionState.REDACTED)
        assert len(redacted) == 1
        assert redacted[0].id == r3.id

    def test_only_project_approved_is_retrievable(self) -> None:
        """is_retrievable returns True only for PROJECT_APPROVED."""
        wf = MemoryPromotionWorkflow()
        record = wf.record(trajectory_id="t1", project_id="p1")
        assert not wf.is_retrievable(record.id)
        wf.redact(record.id)
        assert not wf.is_retrievable(record.id)
        wf.verify_outcome(record.id, tests_pass=True, deploy_success=True)
        assert not wf.is_retrievable(record.id)
        wf.match(record.id)
        wf.generate_insight(record.id)
        wf.review(record.id, reviewer="alice")
        assert not wf.is_retrievable(record.id)
        wf.approve_project(record.id, approver="bob")
        assert wf.is_retrievable(record.id)


# ---------------------------------------------------------------------------
# Task 15: RewardVector
# ---------------------------------------------------------------------------


class TestRewardVector:
    def test_deployment_verified_full_score(self) -> None:
        """Deployment VERIFIED → deployment_success = 1.0."""
        reward = compute_reward(
            completion=True,
            test_pass_rate=1.0,
            has_security_errors=False,
            corrections=0,
            total_steps=3,
            deployment_state="VERIFIED",
            runtime_stability=0.95,
        )
        assert reward.deployment_success == 1.0
        assert reward.runtime_stability == 0.95
        assert reward.completion == 1.0
        assert reward.all_hard_gates_passed is True

    def test_deployment_deployed_half_score(self) -> None:
        """Deployment DEPLOYED (not verified) → deployment_success = 0.5."""
        reward = compute_reward(
            completion=True,
            test_pass_rate=1.0,
            has_security_errors=False,
            corrections=0,
            total_steps=3,
            deployment_state="DEPLOYED",
        )
        assert reward.deployment_success == 0.5

    def test_no_deployment_zero_score(self) -> None:
        """No deployment → deployment_success = 0.0."""
        reward = compute_reward(
            completion=True,
            test_pass_rate=1.0,
            has_security_errors=False,
            corrections=0,
            total_steps=3,
            deployment_state=None,
        )
        assert reward.deployment_success == 0.0

    def test_hard_gate_failure_prevents_promotion(self) -> None:
        """Secret leakage → hard gate fails → all_hard_gates_passed is False."""
        reward = compute_reward(
            completion=True,
            test_pass_rate=1.0,
            has_security_errors=False,
            corrections=0,
            total_steps=3,
            has_secret_leakage=True,
        )
        assert not reward.all_hard_gates_passed
        assert reward.hard_gates["no_secret_leakage"] is False

    def test_overall_score_weighted_average(self) -> None:
        """overall_score is a weighted average of the 7 scalar dimensions."""
        reward = RewardVector(
            structural_validity=1.0,
            unit_tests=1.0,
            security_policy=1.0,
            completion=1.0,
            corrections_needed=1.0,
            deployment_success=1.0,
            runtime_stability=1.0,
        )
        assert reward.overall_score == 1.0

        reward2 = RewardVector()  # all zeros
        assert reward2.overall_score == 0.0

    def test_to_dict_serializable(self) -> None:
        """to_dict() produces a JSON-serializable dict."""
        reward = compute_reward(
            completion=True,
            test_pass_rate=0.8,
            has_security_errors=False,
            corrections=1,
            total_steps=4,
            deployment_state="VERIFIED",
            runtime_stability=0.9,
        )
        d = reward.to_dict()
        assert d["deploymentSuccess"] == 1.0
        assert d["unitTests"] == 0.8
        assert d["hardGates"]["no_secret_leakage"] is True
