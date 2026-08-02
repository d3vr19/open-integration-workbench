"""Tests for the LLM-driven executor (WP-04 Task 3)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from oiw.agent.context import ProjectContext
from oiw.agent.executor import (
    MAX_CORRECTIONS,
    execute_plan,
)
from oiw.agent.gateway_client import ChatResponse, ModelGatewayClient
from oiw.agent.interpreter import NormalizedRequirement
from oiw.agent.planner import ImplementationPlan, PlanStep
from oiw.agent.trajectory import TrajectoryRecorder


def _make_plan(steps: list[PlanStep], base_revision: str) -> ImplementationPlan:
    return ImplementationPlan(
        requirement=NormalizedRequirement(intent="modify-flow", raw="test"),
        steps=steps,
        base_revision=base_revision,
    )


@pytest.mark.asyncio
async def test_execute_happy_path(temp_project: Path, head_sha: str) -> None:
    """3-step plan, all succeed — status COMPLETED."""
    project = ProjectContext.load(temp_project / "order-to-s4")
    plan = _make_plan(
        [
            PlanStep(
                order=1,
                tool="flow.patch",
                arguments={
                    "projectId": "order-to-s4",
                    "flowId": "order-to-s4",
                    "baseRevision": head_sha,
                    "operations": [{"op": "addNode", "node": {"id": "happy-1", "type": "log.message"}}],
                },
            ),
            PlanStep(
                order=2,
                tool="flow.validate",
                arguments={"projectId": "order-to-s4"},
            ),
        ],
        head_sha,
    )
    trajectory = TrajectoryRecorder(
        project_id="order-to-s4",
        task_id="t1",
        base_revision=head_sha,
        persist_dir=temp_project / "traj",
    )
    result = await execute_plan(plan, project, gateway=None, trajectory=trajectory)
    assert result.status == "COMPLETED"
    assert len(result.completed_steps) == 2
    assert result.completed_steps[0].status == "applied"
    # Trajectory has 2 steps recorded
    assert len(trajectory.trajectory.spec.steps) == 2
    trajectory.finalize("success", {})


@pytest.mark.asyncio
async def test_execute_missing_baserevision_returns_conflict(temp_project: Path, head_sha: str) -> None:
    """flow.patch step missing baseRevision — status CONFLICT, no patches applied."""
    project = ProjectContext.load(temp_project / "order-to-s4")
    plan = _make_plan(
        [
            PlanStep(
                order=1,
                tool="flow.patch",
                arguments={
                    "projectId": "order-to-s4",
                    "flowId": "order-to-s4",
                    # Note: no baseRevision
                    "operations": [{"op": "addNode", "node": {"id": "x", "type": "log.message"}}],
                },
            ),
        ],
        head_sha,
    )
    trajectory = TrajectoryRecorder("order-to-s4", "t1", head_sha, persist_dir=temp_project / "traj")
    result = await execute_plan(plan, project, gateway=None, trajectory=trajectory)
    assert result.status == "CONFLICT"
    assert "baseRevision" in (result.error or "")
    assert len(result.completed_steps) == 1
    assert result.completed_steps[0].status == "conflict"


@pytest.mark.asyncio
async def test_execute_bounded_correction_succeeds(temp_project: Path, head_sha: str) -> None:
    """Step 2 fails first, LLM corrects, retry succeeds."""
    project = ProjectContext.load(temp_project / "order-to-s4")
    # First plan step: a flow.patch with an invalid operation (duplicate node ID)
    # that will fail; the LLM corrects to a valid node ID.
    plan = _make_plan(
        [
            PlanStep(
                order=1,
                tool="flow.patch",
                arguments={
                    "projectId": "order-to-s4",
                    "flowId": "order-to-s4",
                    "baseRevision": head_sha,
                    # 'transform' already exists in order-to-s4 -> duplicate ID error
                    "operations": [{"op": "addNode", "node": {"id": "transform", "type": "log.message"}}],
                },
            ),
        ],
        head_sha,
    )
    trajectory = TrajectoryRecorder("order-to-s4", "t1", head_sha, persist_dir=temp_project / "traj")

    # Mock the gateway to return a corrected argument set
    gateway = AsyncMock(spec=ModelGatewayClient)
    gateway.chat.return_value = ChatResponse(
        content=json.dumps(
            {
                "tool": "flow.patch",
                "arguments": {
                    "projectId": "order-to-s4",
                    "flowId": "order-to-s4",
                    "baseRevision": head_sha,
                    "operations": [
                        {"op": "addNode", "node": {"id": "corrected-node", "type": "log.message"}}
                    ],
                },
            }
        ),
    )

    result = await execute_plan(plan, project, gateway=gateway, trajectory=trajectory)
    # The first attempt failed (duplicate ID), the correction succeeded
    assert result.status == "COMPLETED"
    assert len(result.completed_steps) == 1
    assert result.completed_steps[0].status == "applied"
    assert result.completed_steps[0].correction_attempts == 1
    # The corrected node ID is in the result
    assert "corrected-node" in str(result.completed_steps[0].step.arguments)


@pytest.mark.asyncio
async def test_execute_correction_exhausted(temp_project: Path, head_sha: str) -> None:
    """Step fails twice (max corrections) — status FAILED, trajectory records both attempts."""
    project = ProjectContext.load(temp_project / "order-to-s4")
    # Use a flow.patch with a duplicate ID — will fail on every retry
    plan = _make_plan(
        [
            PlanStep(
                order=1,
                tool="flow.patch",
                arguments={
                    "projectId": "order-to-s4",
                    "flowId": "order-to-s4",
                    "baseRevision": head_sha,
                    "operations": [{"op": "addNode", "node": {"id": "transform", "type": "log.message"}}],
                },
            ),
        ],
        head_sha,
    )
    trajectory = TrajectoryRecorder("order-to-s4", "t1", head_sha, persist_dir=temp_project / "traj")

    # Mock the gateway to return the SAME bad arguments (so correction never helps)
    gateway = AsyncMock(spec=ModelGatewayClient)
    gateway.chat.return_value = ChatResponse(
        content=json.dumps(
            {
                "tool": "flow.patch",
                "arguments": {
                    "projectId": "order-to-s4",
                    "flowId": "order-to-s4",
                    "baseRevision": head_sha,
                    # Still duplicate — correction won't help
                    "operations": [{"op": "addNode", "node": {"id": "transform", "type": "log.message"}}],
                },
            }
        ),
    )

    result = await execute_plan(plan, project, gateway=gateway, trajectory=trajectory)
    assert result.status == "FAILED"
    assert len(result.completed_steps) == 1
    assert result.completed_steps[0].status == "failed"
    # MAX_CORRECTIONS attempts were made (each retry fails)
    assert result.completed_steps[0].correction_attempts == MAX_CORRECTIONS


@pytest.mark.asyncio
async def test_execute_max_steps_cap(temp_project: Path, head_sha: str) -> None:
    """Plan with more than max_steps steps — execution halts at max_steps."""
    project = ProjectContext.load(temp_project / "order-to-s4")
    # Build a plan with 5 flow.validate steps (read-only, always succeed)
    plan = _make_plan(
        [
            PlanStep(order=i, tool="flow.validate", arguments={"projectId": "order-to-s4"})
            for i in range(1, 6)
        ],
        head_sha,
    )
    trajectory = TrajectoryRecorder("order-to-s4", "t1", head_sha, persist_dir=temp_project / "traj")
    result = await execute_plan(plan, project, gateway=None, trajectory=trajectory, max_steps=2)
    assert result.status == "FAILED"
    assert "max_steps" in (result.error or "")
    assert len(result.completed_steps) == 2


@pytest.mark.asyncio
async def test_execute_trajectory_records_each_step(temp_project: Path, head_sha: str) -> None:
    """Trajectory has one (observation, action, result) triple per executed step."""
    project = ProjectContext.load(temp_project / "order-to-s4")
    plan = _make_plan(
        [
            PlanStep(
                order=1,
                tool="flow.patch",
                arguments={
                    "projectId": "order-to-s4",
                    "flowId": "order-to-s4",
                    "baseRevision": head_sha,
                    "operations": [{"op": "addNode", "node": {"id": "traj-test-1", "type": "log.message"}}],
                },
            ),
            PlanStep(
                order=2,
                tool="flow.validate",
                arguments={"projectId": "order-to-s4"},
            ),
        ],
        head_sha,
    )
    trajectory = TrajectoryRecorder("order-to-s4", "t1", head_sha, persist_dir=temp_project / "traj")
    await execute_plan(plan, project, gateway=None, trajectory=trajectory)
    assert len(trajectory.trajectory.spec.steps) == 2
    for step in trajectory.trajectory.spec.steps:
        assert step.observation is not None
        assert step.action is not None
        assert step.result is not None
        assert step.action.normalized  # non-empty tuple
        assert step.action.argumentsDigest  # non-empty sha256
