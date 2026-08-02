"""Agent routes — requirement-to-plan and plan-to-implementation endpoints.

Spec ref: §12.2 (Agent Pipeline), §21.1 (POST /projects/{id}/agents:plan,
POST /projects/{id}/agents:implement).
WP-04 Task 6: every flow.patch step now carries baseRevision = current HEAD.
OW-027: POST /agents:implement now returns trajectoryId.
"""

from __future__ import annotations

import subprocess
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agent import execute_plan, interpret_requirement, plan_implementation
from ..workspace import load_project

router = APIRouter(prefix="/api/v1", tags=["Agent"])


class PlanRequest(BaseModel):
    """Request for POST /agents:plan. Spec §21.1."""

    requirement: str
    flowId: str | None = None


class PlanResponse(BaseModel):
    """Response for POST /agents:plan."""

    requirement: dict
    steps: list[dict]
    assumptions: list[str]
    risks: list[str]


class ImplementRequest(BaseModel):
    """Request for POST /agents:implement. Spec §21.1."""

    requirement: str
    flowId: str | None = None
    dryRun: bool = False


class ImplementResponse(BaseModel):
    """Response for POST /agents:implement.

    OW-027: trajectoryId is now returned so the UI can link to
    `oiw trajectory show --id <id>`.
    """

    plan: dict
    stepResults: list[dict]
    success: bool
    errors: list[str]
    trajectoryId: str | None = None


def _git_head_sha(root) -> str:
    """Short HEAD sha of the project's git repo. 'unknown' if no git."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


@router.post("/projects/{project_id}/agents:plan", response_model=PlanResponse)
def plan_endpoint(project_id: str, req: PlanRequest) -> PlanResponse:
    """Generate an implementation plan from a natural-language requirement.

    Spec §12.2: Requirements Interpreter → Integration Planner.
    WP-04 Task 6: baseRevision captured at planning time and injected
    into every flow.patch step.
    """
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc

    base_revision = _git_head_sha(project.root)
    normalized = interpret_requirement(req.requirement)
    plan = plan_implementation(normalized, project_id, req.flowId, base_revision=base_revision)

    return PlanResponse(
        requirement=plan.requirement.to_dict(),
        steps=[s.to_dict() for s in plan.steps],
        assumptions=plan.assumptions,
        risks=plan.risks,
    )


@router.post("/projects/{project_id}/agents:implement", response_model=ImplementResponse)
def implement_endpoint(project_id: str, req: ImplementRequest) -> ImplementResponse:
    """Execute an implementation plan.

    Spec §12.2: Implementation Agent → Validation & Test Agent.
    Spec §12.1: all mutations go through typed patches — the agent never
    edits files directly.
    WP-04 Task 6: baseRevision captured at planning time and injected
    into every flow.patch step.
    OW-027: trajectory recorded and trajectoryId returned.
    """
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc

    base_revision = _git_head_sha(project.root)
    normalized = interpret_requirement(req.requirement)
    plan = plan_implementation(normalized, project_id, req.flowId, base_revision=base_revision)

    if req.dryRun:
        return ImplementResponse(
            plan=plan.to_dict(),
            stepResults=[],
            success=True,
            errors=["dry run — no steps executed"],
            trajectoryId=None,
        )

    result = execute_plan(plan)

    # OW-027: record a trajectory for this implementation.
    # The new TrajectoryRecorder (apps/cli/oiw/agent/trajectory.py) is
    # used to persist a minimal trajectory that captures the requirement,
    # the plan's actions, and the outcome. This closes DEV-020 (trajectory
    # ID not surfaced in UI).
    trajectory_id = _record_trajectory(
        project_id=project_id,
        base_revision=base_revision,
        requirement=req.requirement,
        normalized=normalized,
        plan=plan,
        result=result,
        project_root=project.root,
    )

    return ImplementResponse(
        plan=result.plan.to_dict(),
        stepResults=result.step_results,
        success=result.success,
        errors=result.errors,
        trajectoryId=trajectory_id,
    )


def _record_trajectory(
    project_id: str,
    base_revision: str,
    requirement: str,
    normalized,
    plan,
    result,
    project_root,
) -> str:
    """Record a minimal trajectory for this implementation.

    Uses the TrajectoryRecorder from apps/cli/oiw/agent/trajectory.py.
    Returns the trajectory ID. If recording fails, returns an empty
    string (the API still succeeds — trajectory is a side effect, not
    a hard dependency).
    """
    try:
        # Import lazily so the route doesn't hard-depend on the CLI package
        # being on PYTHONPATH (it is in dev, but might not be in all
        # deployment configs).
        from pathlib import Path

        from oiw.agent.normalization import arguments_digest, normalize_action
        from oiw.agent.trajectory import TrajectoryRecorder

        recorder = TrajectoryRecorder(
            project_id=project_id,
            task_id=f"task-{uuid.uuid4().hex[:8]}",
            base_revision=base_revision,
            persist_dir=Path(project_root) / ".oiw" / "trajectories",
        )
        recorder.set_query(requirement, normalized.to_dict())

        for i, step_result in enumerate(result.step_results):
            # The legacy executor returns step_results as dicts with
            # stepIndex, tool, description, result, success. Reconstruct
            # the minimum needed for the trajectory.
            tool = step_result.get("tool", "unknown")
            success = step_result.get("success", False)
            # The arguments aren't fully echoed back by the legacy executor,
            # so we use the plan step's arguments (which are available).
            step_args = plan.steps[i].arguments if i < len(plan.steps) else {}
            recorder.record_observation(
                step_index=i,
                obs_type="pre-action",
                state={"stepIndex": i, "tool": tool},
            )
            recorder.record_action(
                step_index=i,
                action_type=tool,
                normalized=normalize_action(tool, step_args),
                arguments_digest=arguments_digest(step_args),
                result_status="applied" if success else "failed",
                result_summary=step_result.get("description", ""),
            )

        status = "success" if result.success else "failed"
        recorder.finalize(status, {"completion": 1.0 if result.success else 0.0})
        return recorder.trajectory_id
    except Exception:
        # Trajectory recording is a side effect; don't fail the API call.
        return ""
