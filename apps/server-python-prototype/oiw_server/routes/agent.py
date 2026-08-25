"""Agent routes — requirement-to-plan and plan-to-implementation endpoints.

Spec ref: §12.2 (Agent Pipeline), §21.1 (POST /projects/{id}/agents:plan,
POST /projects/{id}/agents:implement).
WP-04 Task 6: every flow.patch step now carries baseRevision = current HEAD.
OW-027: POST /agents:implement now returns trajectoryId.
OW-032 / WP-08 PR-10: both endpoints consult the durable EMG store and
return a truthful `emg` block (used / confidence / insightId) so the UI's
⚡ EMG-hit badge reflects reality instead of a hardcoded false.
"""

from __future__ import annotations

import logging
import subprocess
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agent import execute_plan, interpret_requirement, plan_implementation
from ..workspace import load_project
from . import emg as emg_routes

logger = logging.getLogger("oiw_server.agent")

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
    # OW-032: truthful EMG retrieval metadata. None when no durable store
    # is loaded; otherwise {used, confidence, insightId, taskId, reason}.
    emg: dict | None = None


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
    emg: dict | None = None


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


def _emg_lookup(project_id: str, requirement_text: str) -> dict | None:
    """Consult the durable EMG store for a matching expert insight (OW-032).

    Read-only lookup — mechanics-first INJECTION stays with the CLI
    orchestrator (`oiw agent`); this route only reports what retrieval
    found so the UI can be honest. Returns None when no durable store is
    loaded (fresh workspaces), so callers can distinguish "no store" from
    "store present but nothing matched".
    """
    store = emg_routes._EMG_STORE
    if store is None:
        return None

    # Normalize with the CLI's deterministic interpreter so component
    # extraction matches what the EMG corpus was built from.
    lookup_req: Any = None
    try:
        from oiw.agent.interpreter import (  # type: ignore[import-not-found]
            interpret_requirement_fallback,
        )

        lookup_req = interpret_requirement_fallback(requirement_text)
    except Exception as exc:
        logger.warning("CLI interpreter unavailable for EMG lookup: %s", exc)

    if lookup_req is None:
        return {
            "used": False,
            "confidence": 0.0,
            "insightId": None,
            "taskId": None,
            "reason": "cli interpreter unavailable",
        }

    try:
        from oiw.emg.retrieval import EMGRetriever  # type: ignore[import-not-found]

        retriever = EMGRetriever(
            store=store._insight_store,
            task_store=store._task_store,
            edge_store=store._edge_store,
            embedder=getattr(store, "_embedder", None),
        )
        result = retriever.retrieve(lookup_req, project_id=project_id)
        return _retrieval_payload(result, store, project_id)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("EMG lookup failed (reporting used=false): %s", exc)
        return {
            "used": False,
            "confidence": 0.0,
            "insightId": None,
            "taskId": None,
            "reason": f"lookup error: {exc}",
        }


def _retrieval_payload(result: Any, store: Any, project_id: str) -> dict:
    """Shape an EMGRetriever result into the API's `emg` block."""
    payload: dict = {
        "used": bool(result.found),
        "confidence": round(float(result.confidence), 4),
        "insightId": None,
        "taskId": None,
        "reason": result.reason,
    }
    if result.insight is not None:
        payload["taskId"] = getattr(result.insight, "task_id", None)
        prov = getattr(result.insight, "provenance", None)
        if prov is not None:
            payload["provenance"] = {
                "expertTrajectoryId": getattr(prov, "expert_trajectory_id", None),
                "matchStage": getattr(prov, "match_stage", None),
            }
        # Resolve the insight's record id (search project-scoped first).
        for scope in (project_id, None):
            for rec in store.list_insights(project_id=scope):
                if rec.insight is result.insight:
                    payload["insightId"] = rec.id
                    break
            if payload["insightId"] is not None:
                break
    return payload


@router.post("/projects/{project_id}/agents:plan", response_model=PlanResponse)
def plan_endpoint(project_id: str, req: PlanRequest) -> PlanResponse:
    """Generate an implementation plan from a natural-language requirement.

    Spec §12.2: Requirements Interpreter → Integration Planner.
    WP-04 Task 6: baseRevision captured at planning time and injected
    into every flow.patch step.
    OW-032: response carries truthful EMG retrieval metadata.
    """
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc

    base_revision = _git_head_sha(project.root)
    normalized = interpret_requirement(req.requirement)
    plan = plan_implementation(normalized, project_id, req.flowId, base_revision=base_revision)
    emg_info = _emg_lookup(project_id, req.requirement)

    return PlanResponse(
        requirement=plan.requirement.to_dict(),
        steps=[s.to_dict() for s in plan.steps],
        assumptions=plan.assumptions,
        risks=plan.risks,
        emg=emg_info,
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
    emg_info = _emg_lookup(project_id, req.requirement)

    if req.dryRun:
        return ImplementResponse(
            plan=plan.to_dict(),
            stepResults=[],
            success=True,
            errors=["dry run — no steps executed"],
            trajectoryId=None,
            emg=emg_info,
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
        emg=emg_info,
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
