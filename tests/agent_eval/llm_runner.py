"""LLM-backed benchmark runner (WP-05 Task 17 / OW-023).

Runs benchmarks against a real LLM (via the z-ai CLI) instead of the
fallback keyword planner. This closes the gap for bench-002 (create
REST-to-HTTP flow) and bench-003 (fix receiver timeout) which the
fallback planner can't satisfy.

The LLM planner:
  1. Reads the benchmark requirement + project context
  2. Sends a structured prompt to `z-ai chat` asking for a JSON plan
  3. Parses the LLM's response into PlanSteps
  4. Executes the plan via the agent orchestrator

Usage:
    python -m tests.agent_eval.llm_runner --benchmark bench-002
    python -m tests.agent_eval.llm_runner --all  # run bench-002 + bench-003
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

# Make the oiw packages importable when running from repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "mcp-server"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "server-python-prototype"))

from oiw.agent.context import ProjectContext  # noqa: E402
from oiw.agent.gateway_client import ModelGatewayClient  # noqa: E402
from oiw.agent.interpreter import (  # noqa: E402
    NormalizedRequirement,
    interpret_requirement_fallback,
)
from oiw.agent.planner import (  # noqa: E402
    ImplementationPlan,
    PlanStep,
    plan_implementation_fallback,
)

from .benchmarks import Benchmark, get_benchmark  # noqa: E402
from .metrics import BenchmarkMetrics, BenchmarkResult, classify_status  # noqa: E402
from .runner import (  # noqa: E402
    _check_expectations,
    _compute_metrics,
    _setup_project,
)


# ---------------------------------------------------------------------------
# z-ai CLI wrapper
# ---------------------------------------------------------------------------


def _call_zai_chat(
    prompt: str, system: str = "You are an expert SAP Cloud Integration developer."
) -> str:
    """Call the z-ai CLI to get an LLM response.

    Returns the raw text content from the LLM's response.
    """
    try:
        result = subprocess.run(
            ["z-ai", "chat", "--prompt", prompt, "--system", system],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            return ""
        # The z-ai CLI outputs JSON. Parse it to extract the content.
        try:
            data = json.loads(result.stdout)
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
        except (json.JSONDecodeError, ValueError, KeyError):
            pass
        return result.stdout
    except Exception:  # noqa: BLE001
        return ""


def _build_planning_prompt(
    benchmark: Benchmark, project_context: ProjectContext, head: str
) -> str:
    """Build the prompt for the LLM planner."""
    return f"""You are an expert SAP Cloud Integration developer. Given the following
requirement and project context, produce a JSON implementation plan.

Requirement: {benchmark.requirement}

Project: {benchmark.project or "new-project"}
Flow ID: {benchmark.flow_id or "auto-detect"}
Current HEAD (baseRevision): {head}

Project context:
{project_context.to_prompt_context(benchmark.flow_id)}

Output a JSON object with this exact shape:
{{
  "steps": [
    {{
      "order": 1,
      "tool": "flow.patch",
      "arguments": {{
        "projectId": "{project_context.project_id}",
        "flowId": "{benchmark.flow_id or "new-flow"}",
        "baseRevision": "{head}",
        "operations": [{{"op": "addNode", "node": {{"id": "...", "type": "...", "config": {{}}}}}}]
      }},
      "rationale": "why this step"
    }}
  ],
  "assumptions": ["..."],
  "risks": ["..."]
}}

Available tools: flow.patch (addNode, removeNode, updateNodeConfig, addEdge, removeEdge),
resource.write, test.create, flow.validate, test.run.

Rules:
- Every flow.patch MUST include baseRevision = "{head}"
- Never include secret values. Use credentialRef.
- Output JSON only, no prose."""


def _parse_llm_plan(
    llm_response: str, requirement: NormalizedRequirement, head: str
) -> ImplementationPlan:
    """Parse the LLM's JSON response into an ImplementationPlan."""
    steps: list[PlanStep] = []
    assumptions: list[str] = []
    risks: list[str] = []

    if not llm_response:
        return ImplementationPlan(
            requirement=requirement,
            steps=[],
            assumptions=["LLM returned empty response"],
            risks=["No plan generated"],
            base_revision=head,
        )

    # Strip markdown fences if present
    text = llm_response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find the first {...} block
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return ImplementationPlan(
                requirement=requirement,
                steps=[],
                assumptions=[],
                risks=["LLM response was not valid JSON"],
                base_revision=head,
            )
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return ImplementationPlan(
                requirement=requirement,
                steps=[],
                assumptions=[],
                risks=["LLM response was not valid JSON"],
                base_revision=head,
            )

    for i, s in enumerate(data.get("steps", []), start=1):
        args = s.get("arguments", {}) or {}
        # Inject baseRevision if missing (defensive)
        if s.get("tool") == "flow.patch" and not args.get("baseRevision"):
            args["baseRevision"] = head
        steps.append(
            PlanStep(
                order=s.get("order", i),
                tool=s.get("tool", "unknown"),
                arguments=args,
                rationale=s.get("rationale", ""),
                depends_on=s.get("depends_on", []) or [],
            )
        )
    assumptions = data.get("assumptions", []) or []
    risks = data.get("risks", []) or []

    return ImplementationPlan(
        requirement=requirement,
        steps=steps,
        assumptions=assumptions,
        risks=risks,
        estimated_patches=sum(1 for s in steps if s.tool == "flow.patch"),
        base_revision=head,
    )


# ---------------------------------------------------------------------------
# LLM-backed benchmark runner
# ---------------------------------------------------------------------------


def run_benchmark_with_llm(
    benchmark: Benchmark,
    workspace: Path,
    persist_dir: Path | None = None,
) -> BenchmarkResult:
    """Run a benchmark using the z-ai LLM planner.

    Args:
        benchmark: The benchmark to run.
        workspace: Temp directory for the project.
        persist_dir: Where to persist trajectories.

    Returns:
        BenchmarkResult with LLM-generated plan + execution metrics.
    """
    start_time = time.monotonic()

    # 1. Set up the project
    try:
        project_path = _setup_project(benchmark, workspace)
    except Exception as exc:  # noqa: BLE001
        return BenchmarkResult(
            benchmark_id=benchmark.id,
            benchmark_name=benchmark.name,
            status="ERROR",
            error=f"project setup failed: {exc}",
            agent_status="ERROR",
        )

    project_context = ProjectContext.load(project_path)
    head = project_context.git_head()

    # 2. Interpret the requirement (using fallback — the LLM planner
    #    handles the actual planning)
    normalized = interpret_requirement_fallback(benchmark.requirement)

    # 3. Call the LLM to generate a plan
    prompt = _build_planning_prompt(benchmark, project_context, head)
    llm_response = _call_zai_chat(prompt)
    plan = _parse_llm_plan(llm_response, normalized, head)

    if not plan.steps:
        # LLM didn't produce a usable plan — fall back
        plan = plan_implementation_fallback(
            normalized, project_context, flow_id=benchmark.flow_id
        )

    # 4. Execute the plan via the orchestrator
    #    We mock the gateway to be unhealthy so the orchestrator uses
    #    our pre-built plan (not its own LLM call).
    gateway = AsyncMock(spec=ModelGatewayClient)
    gateway.health.return_value = False  # force fallback path
    gateway.aclose = AsyncMock()

    # Build a custom execution that uses our LLM-generated plan
    try:
        agent_result = asyncio.run(
            _run_with_custom_plan(
                plan=plan,
                project_path=project_path,
                gateway=gateway,
                persist_dir=persist_dir or (workspace / ".oiw" / "trajectories"),
                benchmark=benchmark,
            )
        )
    except Exception as exc:  # noqa: BLE001
        return BenchmarkResult(
            benchmark_id=benchmark.id,
            benchmark_name=benchmark.name,
            status="ERROR",
            error=f"agent execution failed: {exc}",
            agent_status="ERROR",
            metrics=BenchmarkMetrics(
                latency_ms=int((time.monotonic() - start_time) * 1000),
            ),
        )

    latency_ms = int((time.monotonic() - start_time) * 1000)

    # 5. Check expectations
    expectation_results = _check_expectations(benchmark, project_path, agent_result)

    # 6. Compute metrics
    metrics = _compute_metrics(
        benchmark=benchmark,
        project_path=project_path,
        agent_result=agent_result,
        latency_ms=latency_ms,
        token_cost=0,  # z-ai CLI doesn't report token usage
    )

    # 7. Classify
    status = classify_status(expectation_results, agent_result.status)

    return BenchmarkResult(
        benchmark_id=benchmark.id,
        benchmark_name=benchmark.name,
        status=status,
        metrics=metrics,
        expectation_results=expectation_results,
        agent_status=agent_result.status,
    )


async def _run_with_custom_plan(
    plan: ImplementationPlan,
    project_path: Path,
    gateway: Any,
    persist_dir: Path,
    benchmark: Benchmark,
) -> Any:
    """Execute a pre-built plan via the orchestrator's executor."""
    from oiw.agent.executor import execute_plan
    from oiw.agent.trajectory import TrajectoryRecorder

    trajectory = TrajectoryRecorder(
        project_id=benchmark.id,
        task_id=f"llm-task-{benchmark.id}",
        base_revision=plan.base_revision,
        persist_dir=persist_dir,
    )
    trajectory.set_query(benchmark.requirement, plan.requirement)

    project_context = ProjectContext.load(project_path)
    result = await execute_plan(
        plan=plan,
        project_context=project_context,
        gateway=None,  # no correction attempts
        trajectory=trajectory,
    )

    # Finalize trajectory
    trajectory.finalize(
        result.status.lower() if result.status else "failed",
        {"completion": 1.0 if result.status == "COMPLETED" else 0.0},
    )

    # Return a mock AgentResult-shaped object
    class _MockResult:
        def __init__(self, execution_result, plan, traj_id):
            self.status = execution_result.status
            self.plan = plan
            self.execution = execution_result
            self.trajectory_id = traj_id
            self.warnings = []
            self.normalized_requirement = plan.requirement

    return _MockResult(result, plan, trajectory.trajectory_id)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Run LLM-backed benchmarks. Defaults to bench-002 + bench-003."""
    import argparse

    parser = argparse.ArgumentParser(
        description="OIW LLM-backed benchmark runner (OW-023)."
    )
    parser.add_argument(
        "--benchmark", "-b", help="Run a single benchmark by ID (e.g. bench-002)."
    )
    parser.add_argument("--all", action="store_true", help="Run bench-002 + bench-003.")
    parser.add_argument(
        "--output", "-o", type=Path, default=Path("llm-bench-report.yaml")
    )
    args = parser.parse_args()

    if args.benchmark:
        benchmarks = [get_benchmark(args.benchmark)]
    elif args.all:
        benchmarks = [get_benchmark("bench-002"), get_benchmark("bench-003")]
    else:
        parser.print_help()
        return 1

    import yaml

    results = []
    for bench in benchmarks:
        workspace = Path.cwd() / ".oiw" / "llm-bench" / bench.id
        if workspace.exists():
            shutil.rmtree(workspace)
        result = run_benchmark_with_llm(bench, workspace)
        results.append(result)
        print(f"=== {bench.id} ({bench.name}) ===")
        print(f"  status:       {result.status}")
        print(f"  agent_status: {result.agent_status}")
        m = result.metrics
        print(
            f"  structural={m.structural_correctness:.2f}  tests={m.test_pass_rate:.2f}  latency={m.latency_ms}ms"
        )
        if result.expectation_results:
            for k, v in result.expectation_results.items():
                mark = "✓" if v else "✗"
                print(f"    {mark} {k}")
        if result.error:
            print(f"  error: {result.error}")

    report = {
        "suite": "llm",
        "mode": "z-ai-cli",
        "total": len(results),
        "results": [r.to_dict() for r in results],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        yaml.safe_dump(
            report, sort_keys=False, default_flow_style=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
    print(f"\nReport: {args.output}")
    return 0 if all(r.status in {"PASS", "PARTIAL"} for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["run_benchmark_with_llm", "main"]
