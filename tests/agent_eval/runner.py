"""Benchmark runner (WP-04 Task 8).

Runs a Benchmark against the agent pipeline and produces a BenchmarkResult
with metrics.

Two modes:
  - "fallback": bypasses the gateway; uses the keyword interpreter + hardcoded
    planner directly. This is the CI mode — no LLM, no network, no API key.
  - "llm": uses the full orchestrator with the model gateway. Used in nightly
    or on-demand runs.

The runner is a plain Python module (no pytest) so it can be invoked from
CI as `python -m tests.agent_eval.runner` and produce a YAML report.

Spec ref: §27 (Benchmark Tasks & Evaluation Metrics).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import yaml

# Make the oiw package importable when running from repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "mcp-server"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "server-python-prototype"))

from oiw.agent.gateway_client import ModelGatewayClient  # noqa: E402
from oiw.agent.orchestrator import run_agent  # noqa: E402
from oiw.agent.redaction import Redactor  # noqa: E402

from .benchmarks import (  # noqa: E402
    BENCHMARKS,
    Benchmark,
    ci_benchmarks,
    get_benchmark,
)
from .metrics import (  # noqa: E402
    BenchmarkMetrics,
    BenchmarkResult,
    classify_status,
)

# Registered OIW step types (used to detect hallucinated components).
REGISTERED_STEP_TYPES = {
    "sender.http",
    "receiver.http",
    "sender.sftp",
    "receiver.sftp",
    "validator.json-schema",
    "script.groovy",
    "transform.xslt",
    "router",
    "filter",
    "splitter",
    "gather",
    "encoder.base64",
    "log.message",
    "xml-to-json",
    "json-to-xml",
}


def run_benchmark_fallback(
    benchmark: Benchmark,
    workspace: Path,
    persist_dir: Path | None = None,
) -> BenchmarkResult:
    """Run a benchmark against the fallback planner (no LLM).

    Args:
        benchmark: The benchmark to run.
        workspace: Temp directory to copy/create the project in.
        persist_dir: Where to persist trajectories. Defaults to
            workspace / .oiw / trajectories.

    Returns:
        BenchmarkResult with metrics and expectation checks.
    """
    start_time = time.monotonic()

    # 1. Set up the project under test
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

    # 2. Run the agent in fallback mode (gateway health returns False)
    #    We mock the gateway to avoid any network call.
    gateway = AsyncMock(spec=ModelGatewayClient)
    gateway.health.return_value = False
    gateway.aclose = AsyncMock()

    try:
        agent_result = asyncio.run(
            _run_agent_async(
                benchmark=benchmark,
                project_path=project_path,
                gateway=gateway,
                persist_dir=persist_dir or (workspace / ".oiw" / "trajectories"),
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

    # 3. Check structural expectations against the resulting project state
    expectation_results = _check_expectations(benchmark, project_path, agent_result)

    # 4. Compute metrics
    metrics = _compute_metrics(
        benchmark=benchmark,
        project_path=project_path,
        agent_result=agent_result,
        latency_ms=latency_ms,
        token_cost=0,  # fallback = no tokens
    )

    # 5. Classify PASS/PARTIAL/FAIL
    status = classify_status(expectation_results, agent_result.status)

    return BenchmarkResult(
        benchmark_id=benchmark.id,
        benchmark_name=benchmark.name,
        status=status,
        metrics=metrics,
        expectation_results=expectation_results,
        agent_status=agent_result.status,
    )


async def _run_agent_async(
    benchmark: Benchmark,
    project_path: Path,
    gateway: Any,
    persist_dir: Path,
) -> Any:
    """Invoke run_agent with the fallback gateway."""
    from oiw.agent.orchestrator import AgentResult  # noqa: F401

    return await run_agent(
        requirement=benchmark.requirement,
        project_path=project_path,
        mode="autonomous",  # no approval needed for benchmarks
        flow_id=benchmark.flow_id,
        gateway=gateway,
        persist_dir=persist_dir,
    )


def _setup_project(benchmark: Benchmark, workspace: Path) -> Path:
    """Copy the benchmark's source project (or create a new one) into workspace.

    Returns the path to the project directory (the one containing
    oiw.yaml / flows/, NOT the workspace root).
    """
    workspace.mkdir(parents=True, exist_ok=True)
    if benchmark.project is None:
        # New-project benchmark: scaffold a minimal project skeleton.
        project_dir = workspace / "new-project"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "oiw.yaml").write_text(
            "apiVersion: oiw/v1\nkind: Project\nmetadata:\n  name: new-project\n",
            encoding="utf-8",
        )
        (project_dir / "flows").mkdir(exist_ok=True)
        # Init git so baseRevision is real
        _git_init(project_dir)
        os.environ["OIW_WORKSPACE"] = str(workspace)
        return project_dir
    # Copy the example project
    src = REPO_ROOT / benchmark.project
    if not src.is_dir():
        raise FileNotFoundError(f"benchmark source project not found: {src}")
    project_name = src.name
    dest = workspace / project_name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    _git_init(dest)
    os.environ["OIW_WORKSPACE"] = str(workspace)
    return dest


def _git_init(project_dir: Path) -> None:
    """Init a git repo in the project dir so HEAD is real (WP-04 Task 6)."""
    subprocess.run(["git", "init", "-q"], cwd=project_dir, check=True)
    subprocess.run(["git", "-C", str(project_dir), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(project_dir), "commit", "-q", "-m", "benchmark fixture"],
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "benchmark",
            "GIT_AUTHOR_EMAIL": "benchmark@example.com",
            "GIT_COMMITTER_NAME": "benchmark",
            "GIT_COMMITTER_EMAIL": "benchmark@example.com",
        },
        check=True,
    )


def _check_expectations(
    benchmark: Benchmark,
    project_path: Path,
    agent_result: Any,
) -> dict[str, bool]:
    """Check each structural expectation against the project state.

    Returns a dict of {expectation_name: passed}.
    """
    results: dict[str, bool] = {}
    expected = benchmark.expected

    # Load the (possibly modified) flow IR
    flow_id = benchmark.flow_id or _first_flow_id(project_path)
    flow_data = _load_flow_ir(project_path, flow_id) if flow_id else None
    node_ids = (
        [n["id"] for n in flow_data["spec"]["nodes"]]
        if flow_data and "spec" in flow_data and "nodes" in flow_data["spec"]
        else []
    )

    # nodes_added
    for node_id in expected.nodes_added:
        results[f"nodes_added:{node_id}"] = node_id in node_ids

    # nodes_removed
    for node_id in expected.nodes_removed:
        results[f"nodes_removed:{node_id}"] = node_id not in node_ids

    # resources_added
    for rel_path in expected.resources_added:
        full = project_path / rel_path
        results[f"resources_added:{rel_path}"] = full.is_file()

    # config_changed
    if expected.config_changed and flow_data:
        nodes_by_id = {n["id"]: n for n in flow_data.get("spec", {}).get("nodes", [])}
        for key, expected_val in expected.config_changed.items():
            node_id, config_key = key.split(".", 1)
            node = nodes_by_id.get(node_id, {})
            actual_val = node.get("config", {}).get(config_key)
            results[f"config_changed:{key}"] = actual_val == expected_val

    # flow_created
    if expected.flow_created:
        results["flow_created"] = flow_data is not None and bool(node_ids)

    # has_error_handling
    if expected.has_error_handling and flow_data:
        # Check for errorHandling.defaultExceptionSubprocess in the flow spec
        eh = flow_data.get("spec", {}).get("errorHandling", {})
        results["has_error_handling"] = "defaultExceptionSubprocess" in eh

    # validation_passes
    if expected.validation_passes:
        results["validation_passes"] = _run_validation(project_path)

    # tests_pass
    if expected.tests_pass:
        results["tests_pass"] = _run_tests(project_path, flow_id) if flow_id else False

    # tests_added
    if expected.tests_added:
        actual = _count_tests(project_path, flow_id) if flow_id else 0
        results["tests_added"] = actual >= expected.tests_added

    # Agent must not be in REJECTED/CONFLICT/ERROR state
    results["agent_status_ok"] = agent_result.status in {"COMPLETED"}

    return results


def _load_flow_ir(project_path: Path, flow_id: str | None) -> dict[str, Any] | None:
    """Load and parse a flow's flow.yaml."""
    if not flow_id:
        return None
    p = project_path / "flows" / flow_id / "flow.yaml"
    if not p.is_file():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _first_flow_id(project_path: Path) -> str | None:
    """Return the first flow ID in the project, or None."""
    flows_dir = project_path / "flows"
    if not flows_dir.is_dir():
        return None
    for d in sorted(flows_dir.iterdir()):
        if d.is_dir() and (d / "flow.yaml").is_file():
            return d.name
    return None


def _run_validation(project_path: Path) -> bool:
    """Run `oiw validate --strict --json` and return True if 0 errors.

    WP-05 OW-024: uses structured JSON output instead of text parsing.
    """
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "oiw.cli",
                "validate",
                "--strict",
                "--json",
                "--project",
                str(project_path),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True
        # Parse JSON to check if it's a real validation failure vs a crash
        try:
            data = json.loads(result.stdout)
            return data.get("passed", False)
        except (json.JSONDecodeError, ValueError):
            return False
    except Exception:  # noqa: BLE001
        return False


def _run_tests(project_path: Path, flow_id: str) -> bool:
    """Run `oiw test --all --json` and return True if all tests pass.

    WP-05 OW-024: uses structured JSON output instead of text parsing.
    """
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "oiw.cli",
                "test",
                "--all",
                "--json",
                "--project",
                str(project_path),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True
        try:
            data = json.loads(result.stdout)
            return data.get("passed", False)
        except (json.JSONDecodeError, ValueError):
            return False
    except Exception:  # noqa: BLE001
        return False


def _count_tests(project_path: Path, flow_id: str) -> int:
    """Count test YAML files under flows/{flow_id}/tests/."""
    tests_dir = project_path / "flows" / flow_id / "tests"
    if not tests_dir.is_dir():
        return 0
    return sum(
        1 for f in tests_dir.iterdir() if f.suffix in {".yaml", ".yml"} and f.is_file()
    )


def _compute_metrics(
    benchmark: Benchmark,
    project_path: Path,
    agent_result: Any,
    latency_ms: int,
    token_cost: int,
) -> BenchmarkMetrics:
    """Compute the metrics vector for a benchmark run."""
    # structural_correctness: fraction of expectation_results that passed
    exp_results = _check_expectations(benchmark, project_path, agent_result)
    if exp_results:
        passed = sum(1 for v in exp_results.values() if v)
        structural = passed / len(exp_results)
    else:
        structural = 0.0

    # test_pass_rate: from oiw test output
    test_pass_rate = _compute_test_pass_rate(project_path, benchmark.flow_id)

    # policy_violations: from oiw validate output (count "error" lines)
    policy_violations = _count_policy_violations(project_path)

    # hallucinated_components: count of step types in the plan that are NOT registered
    hallucinated = 0
    if agent_result.plan:
        for step in agent_result.plan.steps:
            if step.tool == "flow.patch":
                for op in step.arguments.get("operations", []):
                    node = op.get("node", {})
                    node_type = node.get("type", "")
                    if node_type and node_type not in REGISTERED_STEP_TYPES:
                        hallucinated += 1

    # secret_handling_violations: scan the trajectory YAML for unredacted secrets
    secret_violations = _count_secret_violations(
        agent_result.trajectory_id, project_path
    )

    return BenchmarkMetrics(
        structural_correctness=structural,
        test_pass_rate=test_pass_rate,
        policy_violations=policy_violations,
        human_corrections=0,  # always 0 in fallback/CI
        token_cost=token_cost,
        latency_ms=latency_ms,
        hallucinated_components=hallucinated,
        secret_handling_violations=secret_violations,
        trajectory_id=agent_result.trajectory_id,
    )


def _compute_test_pass_rate(project_path: Path, flow_id: str | None) -> float:
    """Run oiw test --json and parse the pass rate.

    WP-05 OW-024: uses structured JSON output instead of text parsing.
    """
    if not flow_id:
        return 0.0
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "oiw.cli",
                "test",
                "--all",
                "--json",
                "--project",
                str(project_path),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        # WP-05 OW-024: parse structured JSON instead of regex on text output
        try:
            data = json.loads(result.stdout)
            return data.get("pass_rate", 0.0)
        except (json.JSONDecodeError, ValueError):
            # Fallback: return code based
            return 1.0 if result.returncode == 0 else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def _count_policy_violations(project_path: Path) -> int:
    """Run oiw validate --strict --json and count error diagnostics.

    WP-05 OW-024: uses structured JSON output instead of counting
    'ERROR' lines in text output.
    """
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "oiw.cli",
                "validate",
                "--strict",
                "--json",
                "--project",
                str(project_path),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        # WP-05 OW-024: parse structured JSON to get exact error count
        try:
            data = json.loads(result.stdout)
            return data.get("error_count", 0)
        except (json.JSONDecodeError, ValueError):
            # Fallback: count ERROR lines in stderr (old behavior)
            return sum(
                1 for line in result.stderr.splitlines() if "ERROR" in line.upper()
            )
    except Exception:  # noqa: BLE001
        return 0


def _count_secret_violations(trajectory_id: str, project_path: Path) -> int:
    """Scan the trajectory YAML for unredacted secrets.

    Uses the same Redactor patterns; if applying the redactor changes
    the file, that's a violation.
    """
    if not trajectory_id:
        return 0
    traj_path = project_path / ".oiw" / "trajectories" / f"{trajectory_id}.yaml"
    if not traj_path.is_file():
        return 0
    original = traj_path.read_text(encoding="utf-8")
    redacted = Redactor().redact(original)
    if redacted != original:
        # Count how many [REDACTED_*] tokens were inserted
        return redacted.count("[REDACTED") - original.count("[REDACTED")
    return 0


# ---------------------------------------------------------------------------
# CLI entry point: `python -m tests.agent_eval.runner`
# ---------------------------------------------------------------------------


def run_ci_suite(output_path: Path | None = None) -> dict[str, Any]:
    """Run the CI benchmark suite (bench-001 to bench-003) and return a report.

    Args:
        output_path: If provided, write the report as YAML to this path.

    Returns:
        The report as a dict.
    """
    benchmarks = ci_benchmarks()
    results: list[BenchmarkResult] = []
    for bench in benchmarks:
        # Each benchmark gets its own temp workspace
        workspace = Path.cwd() / ".oiw" / "agent-eval" / bench.id
        if workspace.exists():
            shutil.rmtree(workspace)
        result = run_benchmark_fallback(bench, workspace)
        results.append(result)

    # Aggregate
    passed = sum(1 for r in results if r.status == "PASS")
    partial = sum(1 for r in results if r.status == "PARTIAL")
    failed = sum(1 for r in results if r.status == "FAIL")
    errored = sum(1 for r in results if r.status == "ERROR")

    report = {
        "suite": "ci",
        "mode": "fallback",
        "total": len(results),
        "passed": passed,
        "partial": partial,
        "failed": failed,
        "errored": errored,
        "results": [r.to_dict() for r in results],
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            yaml.safe_dump(
                report, sort_keys=False, default_flow_style=False, allow_unicode=True
            ),
            encoding="utf-8",
        )

    return report


def main() -> int:
    """CLI entry point. Runs the CI suite and prints a summary.

    Exit code: 0 if all benchmarks PASS or PARTIAL, 1 if any FAIL or ERROR.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="OIW agent evaluation harness (WP-04 Task 8)."
    )
    parser.add_argument(
        "--benchmark",
        "-b",
        help="Run a single benchmark by ID (e.g. bench-001). Default: run CI suite (bench-001..003).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("agent-eval-report.yaml"),
        help="Output YAML report path (default: agent-eval-report.yaml).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all benchmarks and exit.",
    )
    args = parser.parse_args()

    if args.list:
        for b in BENCHMARKS:
            tag_str = ",".join(b.tags) if b.tags else "-"
            llm_str = "LLM" if b.requires_llm else "fallback"
            print(f"  {b.id}  [{llm_str:8s}] [{tag_str:32s}]  {b.name}")
        return 0

    if args.benchmark:
        bench = get_benchmark(args.benchmark)
        workspace = Path.cwd() / ".oiw" / "agent-eval" / bench.id
        if workspace.exists():
            shutil.rmtree(workspace)
        result = run_benchmark_fallback(bench, workspace)
        report = {
            "suite": "single",
            "mode": "fallback",
            "results": [result.to_dict()],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            yaml.safe_dump(
                report, sort_keys=False, default_flow_style=False, allow_unicode=True
            ),
            encoding="utf-8",
        )
        print(f"=== {bench.id} ({bench.name}) ===")
        print(f"  status:       {result.status}")
        print(f"  agent_status: {result.agent_status}")
        print("  metrics:")
        for k, v in result.metrics.to_dict().items():
            print(f"    {k}: {v}")
        print("  expectations:")
        for k, v in result.expectation_results.items():
            mark = "✓" if v else "✗"
            print(f"    {mark} {k}")
        if result.error:
            print(f"  error: {result.error}")
        return 0 if result.status in {"PASS", "PARTIAL"} else 1

    # Default: run CI suite
    report = run_ci_suite(args.output)
    print("=== CI Benchmark Suite (fallback mode) ===")
    print(f"  total:   {report['total']}")
    print(f"  passed:  {report['passed']}")
    print(f"  partial: {report['partial']}")
    print(f"  failed:  {report['failed']}")
    print(f"  errored: {report['errored']}")
    print()
    for r in report["results"]:
        m = r["metrics"]
        print(
            f"  {r['benchmarkId']}  {r['status']:8s}  "
            f"structural={m['structural_correctness']:.2f}  "
            f"tests={m['test_pass_rate']:.2f}  "
            f"latency={m['latency_ms']}ms  "
            f"tokens={m['token_cost']}"
        )
    print(f"\nReport written to: {args.output}")
    # Exit code: 0 if no benchmark ERRORED (harness failure). bench-002/003
    # are EXPECTED to FAIL/PARTIAL in fallback mode — that's not a harness
    # failure, just a known limitation. The regression gate (bench-001 must
    # PASS) is enforced by the CI workflow's separate gate step.
    return 0 if report["errored"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "BenchmarkMetrics",
    "BenchmarkResult",
    "run_benchmark_fallback",
    "run_ci_suite",
]
