"""Agent routes — requirement-to-plan and plan-to-implementation endpoints.

Spec ref: §12.2 (Agent Pipeline), §21.1 (POST /projects/{id}/agents:plan,
POST /projects/{id}/agents:implement).
"""

from __future__ import annotations

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
    """Response for POST /agents:implement."""

    plan: dict
    stepResults: list[dict]
    success: bool
    errors: list[str]


@router.post("/projects/{project_id}/agents:plan", response_model=PlanResponse)
def plan_endpoint(project_id: str, req: PlanRequest) -> PlanResponse:
    """Generate an implementation plan from a natural-language requirement.

    Spec §12.2: Requirements Interpreter → Integration Planner.
    """
    try:
        load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc

    normalized = interpret_requirement(req.requirement)
    plan = plan_implementation(normalized, project_id, req.flowId)

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
    """
    try:
        load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc

    normalized = interpret_requirement(req.requirement)
    plan = plan_implementation(normalized, project_id, req.flowId)

    if req.dryRun:
        return ImplementResponse(
            plan=plan.to_dict(),
            stepResults=[],
            success=True,
            errors=["dry run — no steps executed"],
        )

    result = execute_plan(plan)
    return ImplementResponse(
        plan=result.plan.to_dict(),
        stepResults=result.step_results,
        success=result.success,
        errors=result.errors,
    )
