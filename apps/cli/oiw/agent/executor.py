"""LLM-driven plan executor (WP-04 Task 3).

Applies plan steps sequentially. For each step:
  1. Record a pre-action observation (current project snapshot).
  2. Validate baseRevision for flow.patch steps (reject if stale).
  3. Dispatch the tool call via the MCP dispatcher.
  4. Record the action + result in the trajectory.
  5. On failure, request a corrected tool call from the LLM (bounded:
     max 2 retries per step). If both retries fail, halt the plan.

Spec refs: §15.13 (bounded correction — NOT an unbounded reflection loop),
§12.1 (LLM never edits files directly; all mutations go through typed
patches), §15.4 (action normalization for trajectory).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .context import ProjectContext
from .gateway_client import ChatResponse, ModelGatewayClient
from .normalization import arguments_digest, normalize_action
from .planner import ImplementationPlan, PlanStep
from .trajectory import TrajectoryRecorder


# Maximum correction attempts per failed step (spec §15.13: bounded).
MAX_CORRECTIONS = 2


@dataclass
class StepResult:
    """Result of executing a single plan step."""

    step: PlanStep
    status: str                            # applied | failed | skipped | conflict
    summary: str = ""
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    correction_attempts: int = 0
    raw_result: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step.to_dict(),
            "status": self.status,
            "summary": self.summary,
            "diagnostics": self.diagnostics,
            "correctionAttempts": self.correction_attempts,
        }


@dataclass
class ExecutionResult:
    """Result of executing an entire plan."""

    status: str                            # COMPLETED | FAILED | CONFLICT | REJECTED
    completed_steps: list[StepResult] = field(default_factory=list)
    error: str | None = None
    trajectory_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "completedSteps": [s.to_dict() for s in self.completed_steps],
            "error": self.error,
            "trajectoryId": self.trajectory_id,
        }


def _dispatch_tool(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call via the MCP tool dispatcher.

    The dispatcher lives in `oiw_mcp.tools`. It returns a JSON string;
    we parse it here so the executor can inspect status fields.
    """
    try:
        from oiw_mcp.tools import dispatch_tool  # type: ignore[import-not-found]
    except ImportError as exc:
        return {"error": f"MCP dispatcher unavailable: {exc}", "applied": 0}
    try:
        result_text = dispatch_tool(tool, arguments)
        try:
            return json.loads(result_text)
        except json.JSONDecodeError:
            return {"raw": result_text}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "applied": 0}


def _result_status(parsed: dict[str, Any], tool: str) -> tuple[str, str]:
    """Classify a dispatcher result into (status, summary)."""
    if not isinstance(parsed, dict):
        return "failed", "non-dict result"
    if parsed.get("status") == "CONFLICT":
        return "conflict", parsed.get("error", "baseRevision conflict")
    if parsed.get("code") == -32602:
        return "conflict", parsed.get("error", "invalid params (likely missing/stale baseRevision)")
    if "error" in parsed:
        return "failed", str(parsed["error"])
    if tool == "flow.validate":
        # flow.validate returns errors[] + warnings[]; treat empty errors as success
        errors = parsed.get("errors", [])
        return ("applied" if not errors else "failed"), f"errors={len(errors)} warnings={len(parsed.get('warnings', []))}"
    if tool == "test.run":
        # test.run returns pass/fail counts
        passed = parsed.get("passed", 0)
        failed = parsed.get("failed", 0)
        return ("applied" if failed == 0 else "failed"), f"passed={passed} failed={failed}"
    return "applied", f"applied={parsed.get('applied', '?')}"


async def _request_correction(
    gateway: ModelGatewayClient,
    step: PlanStep,
    failure_summary: str,
    failure_diagnostics: list[dict[str, Any]],
    project_context: ProjectContext,
    head_revision: str,
) -> dict[str, Any] | None:
    """Ask the LLM to produce corrected arguments for a failed step.

    Returns the corrected arguments dict, or None if the LLM could not
    produce a usable correction.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a tool-call corrector. The previous tool call failed. "
                "Produce a corrected JSON object with the same `tool` name and a "
                "revised `arguments` dict. Output JSON only: "
                '{"tool": "...", "arguments": {...}}. '
                "Constraints: baseRevision must equal the provided HEAD; no secrets."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Failed tool: {step.tool}\n"
                f"Failed arguments: {json.dumps(step.arguments, default=str)}\n"
                f"Failure: {failure_summary}\n"
                f"Diagnostics: {json.dumps(failure_diagnostics, default=str)}\n"
                f"Current HEAD: {head_revision}\n"
                f"Project: {project_context.project_id}\n"
                "Produce corrected arguments as JSON."
            ),
        },
    ]
    try:
        response: ChatResponse = await gateway.chat(
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=2048,
            temperature=0.1,
        )
    except Exception:
        return None
    if not response.content:
        return None
    import re

    text = response.content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    corrected_args = data.get("arguments") or data.get("args") or data
    if not isinstance(corrected_args, dict):
        return None
    # Re-inject baseRevision for flow.patch (defensive)
    if step.tool == "flow.patch" and not corrected_args.get("baseRevision"):
        corrected_args["baseRevision"] = head_revision
    return corrected_args


async def execute_plan(
    plan: ImplementationPlan,
    project_context: ProjectContext,
    gateway: ModelGatewayClient | None,
    trajectory: TrajectoryRecorder,
    max_steps: int = 20,
) -> ExecutionResult:
    """Execute an implementation plan step-by-step.

    Args:
        plan: The plan to execute.
        project_context: Project being modified.
        gateway: LLM gateway client (used for bounded correction; may be
            None in fallback-only mode, in which case corrections are
            skipped).
        trajectory: Trajectory recorder (already initialized with the
            same base_revision as `plan.base_revision`).
        max_steps: Hard cap on step count (spec §15.13).

    Returns:
        ExecutionResult with status COMPLETED | FAILED | CONFLICT.
    """
    results: list[StepResult] = []
    head_revision = plan.base_revision or project_context.git_head()

    for i, step in enumerate(plan.steps):
        if i >= max_steps:
            return ExecutionResult(
                status="FAILED",
                completed_steps=results,
                error=f"max_steps ({max_steps}) reached",
                trajectory_id=trajectory.trajectory_id,
            )

        # 1. Pre-action observation
        trajectory.record_observation(
            step_index=i,
            obs_type="pre-action",
            state=project_context.snapshot(),
        )

        # 2. baseRevision validation for flow.patch steps (Task 6 enforcement
        # in the executor itself, before we even hit the MCP dispatcher)
        if step.tool == "flow.patch":
            br = step.arguments.get("baseRevision")
            if not br:
                err = "flow.patch step missing baseRevision"
                trajectory.record_action(
                    step_index=i,
                    action_type=step.tool,
                    normalized=normalize_action(step.tool, step.arguments),
                    arguments_digest=arguments_digest(step.arguments),
                    result_status="conflict",
                    result_summary=err,
                )
                results.append(
                    StepResult(
                        step=step,
                        status="conflict",
                        summary=err,
                        diagnostics=[],
                        correction_attempts=0,
                        raw_result=None,
                    )
                )
                return ExecutionResult(
                    status="CONFLICT",
                    completed_steps=results,
                    error=err,
                    trajectory_id=trajectory.trajectory_id,
                )
            # The MCP dispatcher will compare against current HEAD;
            # we don't re-check here because the workspace may have been
            # mutated by previous steps in this same execution (and we
            # have not committed). The HEAD doesn't change mid-execution
            # because we don't commit until the operator approves.

        # 3. Dispatch + 4. Record (with bounded correction)
        current_args = step.arguments
        correction_attempts = 0  # number of LLM corrections requested
        final_status = "failed"
        final_summary = ""
        final_diagnostics: list[dict[str, Any]] = []
        final_raw: Any = None

        while True:
            parsed = _dispatch_tool(step.tool, current_args)
            final_raw = parsed
            status, summary = _result_status(parsed, step.tool)
            final_status, final_summary = status, summary
            final_diagnostics = parsed.get("diagnostics", []) if isinstance(parsed, dict) else []

            if status == "applied" or status == "skipped":
                break
            if status == "conflict":
                # No point retrying a conflict — caller must re-fetch HEAD.
                break
            # status == "failed" — try correction if we have a gateway and budget
            if gateway is None or correction_attempts >= MAX_CORRECTIONS:
                break
            corrected = await _request_correction(
                gateway, step, summary, final_diagnostics, project_context, head_revision
            )
            if corrected is None:
                break
            correction_attempts += 1
            current_args = corrected

        # 5. Record the action
        trajectory.record_action(
            step_index=i,
            action_type=step.tool,
            normalized=normalize_action(step.tool, current_args),
            arguments_digest=arguments_digest(current_args),
            result_status=final_status,
            result_summary=final_summary,
            diagnostics=final_diagnostics,
        )

        results.append(
            StepResult(
                step=PlanStep(
                    order=step.order,
                    tool=step.tool,
                    arguments=current_args,
                    rationale=step.rationale,
                    depends_on=step.depends_on,
                ),
                status=final_status,
                summary=final_summary,
                diagnostics=final_diagnostics,
                correction_attempts=correction_attempts,
                raw_result=final_raw,
            )
        )

        if final_status == "conflict":
            return ExecutionResult(
                status="CONFLICT",
                completed_steps=results,
                error=final_summary,
                trajectory_id=trajectory.trajectory_id,
            )
        if final_status == "failed" and step.tool != "flow.validate":
            # Halt on failure (except flow.validate, which is read-only and
            # reports issues we want the rest of the plan to react to).
            return ExecutionResult(
                status="FAILED",
                completed_steps=results,
                error=f"step {step.order} ({step.tool}) failed: {final_summary}",
                trajectory_id=trajectory.trajectory_id,
            )

    return ExecutionResult(
        status="COMPLETED",
        completed_steps=results,
        trajectory_id=trajectory.trajectory_id,
    )


__all__ = [
    "StepResult",
    "ExecutionResult",
    "execute_plan",
    "MAX_CORRECTIONS",
]
