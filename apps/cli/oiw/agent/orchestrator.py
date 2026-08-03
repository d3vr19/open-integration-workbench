"""Agent orchestrator — top-level entry point (WP-04 Task 7).

Chains: interpreter → planner → (approval) → executor → trajectory.

Two modes:
  - "co-pilot" (default): presents plan, waits for approval callback.
  - "autonomous": executes without approval (still validates).

CLI integration (planned, see WP-04 §3 Task 7):
    oiw agent "Add JSON schema validation to order-to-s4"
    oiw agent --mode autonomous "..."
    oiw trajectory show --last
    oiw trajectory export --redacted --output traj-export.yaml
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .context import ProjectContext
from .executor import ExecutionResult, execute_plan
from .gateway_client import ModelGatewayClient
from .interpreter import (
    OIW_W014,
    NormalizedRequirement,
    interpret_requirement,
    interpret_requirement_fallback,
)
from .planner import (
    OIW_W014_PLANNER,
    ImplementationPlan,
    plan_implementation,
    plan_implementation_fallback,
)
from .trajectory import TrajectoryRecorder

# Type for the approval callback. Receives the plan; returns True to
# proceed, False to abort. In co-pilot mode the CLI/UI supplies a
# callback that prompts the user; in tests it can be a lambda.
ApprovalCallback = Callable[[ImplementationPlan], Awaitable[bool]]


@dataclass
class AgentResult:
    """Top-level result returned by `run_agent`."""

    status: str  # COMPLETED | FAILED | CONFLICT | REJECTED | FALLBACK
    plan: ImplementationPlan | None = None
    execution: ExecutionResult | None = None
    trajectory_id: str = ""
    warnings: list[str] = field(default_factory=list)
    normalized_requirement: NormalizedRequirement | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "plan": self.plan.to_dict() if self.plan else None,
            "execution": self.execution.to_dict() if self.execution else None,
            "trajectoryId": self.trajectory_id,
            "warnings": self.warnings,
            "normalizedRequirement": self.normalized_requirement.to_dict()
            if self.normalized_requirement
            else None,
        }


async def _noop_approval(plan: ImplementationPlan) -> bool:
    """Default approval callback: autonomous mode, always approves."""
    return True


async def run_agent(
    requirement: str,
    project_path: Path | str,
    mode: str = "co-pilot",
    flow_id: str | None = None,
    gateway: ModelGatewayClient | None = None,
    approval_callback: ApprovalCallback | None = None,
    persist_dir: Path | str | None = None,
    emg_retriever: Any = None,
) -> AgentResult:
    """Run the full agent pipeline: interpret → (retrieve EMG) → plan → (approve) → execute.

    Args:
        requirement: Natural-language requirement.
        project_path: Path to the project on disk.
        mode: "co-pilot" (default; presents plan for approval) or
            "autonomous" (executes without approval).
        flow_id: Optional target flow ID.
        gateway: Optional pre-configured gateway client. If None, a new
            one is created from env vars. If the gateway is unreachable,
            the orchestrator falls back to keyword interpretation + the
            hardcoded planner and emits warning OIW-W014.
        approval_callback: Async callable invoked in co-pilot mode with
            the proposed plan. Defaults to "always approve" (autonomous).
        persist_dir: Optional override for trajectory persistence dir
            (used by tests to write to tmp_path).
        emg_retriever: Optional EMGRetriever. If provided, the orchestrator
            checks the EMG insight store for a matching expert trajectory
            BEFORE invoking the LLM/keyword planner. If a match is found,
            the expert's successful_workflow is injected directly into the
            plan (mechanics-first, no LLM call needed). Spec §15.11-15.12.

    Returns:
        AgentResult with status, plan, execution, trajectory_id, warnings.
    """
    project_context = ProjectContext.load(project_path)
    base_revision = project_context.git_head()
    warnings: list[str] = []

    owns_gateway = gateway is None
    if owns_gateway:
        gateway = ModelGatewayClient(project_id=project_context.project_id)

    trajectory = TrajectoryRecorder(
        project_id=project_context.project_id,
        task_id=f"task-{uuid.uuid4().hex[:8]}",
        base_revision=base_revision,
        persist_dir=persist_dir,
    )

    try:
        # 1. Interpret
        gw_healthy = await gateway.health() if gateway is not None else False
        if gw_healthy:
            try:
                normalized = await interpret_requirement(requirement, project_context, gateway)
            except Exception as exc:
                warnings.append(f"{OIW_W014} (cause: {exc})")
                normalized = interpret_requirement_fallback(requirement)
        else:
            warnings.append(OIW_W014)
            normalized = interpret_requirement_fallback(requirement)

        trajectory.set_query(requirement, normalized)

        # 1.5. EMG retrieval (mechanics-first loop, spec §15.11-15.12)
        emg_used = False
        if emg_retriever is not None:
            from ..emg.retrieval import inject_insight_into_plan

            retrieval = emg_retriever.retrieve(
                requirement=normalized,
                project_id=project_context.project_id,
            )
            if retrieval.found and retrieval.insight is not None:
                # Inject the expert's successful_workflow into the plan
                injected_steps = inject_insight_into_plan(
                    insight=retrieval.insight,
                    base_revision=base_revision,
                    project_id=project_context.project_id,
                    flow_id=flow_id,
                )
                if injected_steps:
                    from .planner import PlanStep

                    plan_steps = [
                        PlanStep(
                            order=s["order"],
                            tool=s["tool"],
                            arguments=s["arguments"],
                            rationale=s["rationale"],
                            depends_on=s.get("depends_on", []),
                        )
                        for s in injected_steps
                    ]
                    plan = ImplementationPlan(
                        requirement=normalized,
                        steps=plan_steps,
                        assumptions=[
                            f"EMG-retrieved from expert trajectory (confidence={retrieval.confidence:.2f})"
                        ],
                        risks=[],
                        estimated_patches=sum(1 for s in plan_steps if s.tool == "flow.patch"),
                        base_revision=base_revision,
                    )
                    emg_used = True
                    warnings.append(
                        f"OIW-I001: EMG insight retrieved (confidence={retrieval.confidence:.2f}); using expert workflow instead of LLM planner"
                    )

        # 2. Plan (only if EMG didn't provide one)
        if not emg_used:
            if gw_healthy:
                try:
                    plan = await plan_implementation(normalized, project_context, gateway, flow_id=flow_id)
                except Exception as exc:
                    warnings.append(f"{OIW_W014_PLANNER} (cause: {exc})")
                    plan = plan_implementation_fallback(normalized, project_context, flow_id=flow_id)
            else:
                warnings.append(OIW_W014_PLANNER)
                plan = plan_implementation_fallback(normalized, project_context, flow_id=flow_id)

        # 3. Approval (co-pilot mode)
        if mode == "co-pilot":
            cb = approval_callback or _noop_approval
            approved = await cb(plan)
            if not approved:
                trajectory.finalize("rejected", {"reason": "user_rejected_plan"})
                return AgentResult(
                    status="REJECTED",
                    plan=plan,
                    trajectory_id=trajectory.trajectory_id,
                    warnings=warnings,
                    normalized_requirement=normalized,
                )

        # 4. Execute
        execution = await execute_plan(
            plan=plan,
            project_context=project_context,
            gateway=gateway if gw_healthy else None,
            trajectory=trajectory,
        )

        # 5. Reward (spec §15.6: outcome reward vector)
        reward = _compute_reward(execution)
        trajectory.finalize(execution.status.lower() if execution.status else "failed", reward)

        return AgentResult(
            status=execution.status,
            plan=plan,
            execution=execution,
            trajectory_id=trajectory.trajectory_id,
            warnings=warnings,
            normalized_requirement=normalized,
        )
    finally:
        if owns_gateway and gateway is not None:
            await gateway.aclose()


def _compute_reward(execution: ExecutionResult) -> dict[str, Any]:
    """Compute the reward vector for a completed execution.

    Spec §15.6: reward is a vector of scalar signals, not a single
    scalar. We compute:
      - structural_correctness: fraction of steps that applied cleanly
      - completion: 1.0 if status COMPLETED, 0.0 otherwise
      - corrections_needed: total correction attempts across all steps
      - conflict_count: number of CONFLICT-status steps
    """
    if not execution.completed_steps:
        return {
            "structural_correctness": 0.0,
            "completion": 1.0 if execution.status == "COMPLETED" else 0.0,
            "corrections_needed": 0,
            "conflict_count": 0,
        }
    applied = sum(1 for s in execution.completed_steps if s.status == "applied")
    corrections = sum(s.correction_attempts for s in execution.completed_steps)
    conflicts = sum(1 for s in execution.completed_steps if s.status == "conflict")
    return {
        "structural_correctness": applied / len(execution.completed_steps),
        "completion": 1.0 if execution.status == "COMPLETED" else 0.0,
        "corrections_needed": corrections,
        "conflict_count": conflicts,
    }


__all__ = ["run_agent", "AgentResult", "ApprovalCallback"]
