"""Metrics collected per benchmark run (WP-04 Task 8, spec §27).

Each benchmark produces a `BenchmarkResult` with a `metrics` dict containing:
  - structural_correctness: 0.0-1.0 (fraction of structural expectations met)
  - test_pass_rate: 0.0-1.0 (fraction of project tests that pass after execution)
  - policy_violations: int (count of policy rule violations after execution)
  - human_corrections: int (always 0 in fallback/CI; nonzero only in human-eval mode)
  - token_cost: int (0 for fallback; from gateway usage for LLM runs)
  - latency_ms: int (wall-clock duration of the agent run)
  - hallucinated_components: int (count of step types not in the registry)
  - secret_handling_violations: int (count of secrets found in trajectory YAML)
  - trajectory_id: str (links to the persisted trajectory file)

The metrics are designed to be comparable across runs and across
configurations (fallback vs LLM). A regression in any metric triggers
a CI failure.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class BenchmarkMetrics:
    """Metrics vector for a single benchmark run (spec §27)."""

    structural_correctness: float = 0.0
    test_pass_rate: float = 0.0
    policy_violations: int = 0
    human_corrections: int = 0
    token_cost: int = 0
    latency_ms: int = 0
    hallucinated_components: int = 0
    secret_handling_violations: int = 0
    trajectory_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkResult:
    """Result of running one benchmark.

    `status` is one of:
      - PASS: all expectations met, all metrics above threshold
      - PARTIAL: some expectations met (e.g. node added but validation fails)
      - FAIL: agent did not produce any of the expected changes
      - ERROR: benchmark harness itself failed (exception, missing project, ...)
      - SKIP: benchmark skipped (e.g. requires_llm in CI)
    """

    benchmark_id: str
    benchmark_name: str
    status: str                           # PASS | PARTIAL | FAIL | ERROR | SKIP
    metrics: BenchmarkMetrics = field(default_factory=BenchmarkMetrics)
    expectation_results: dict[str, bool] = field(default_factory=dict)
    error: str | None = None
    agent_status: str = ""                # COMPLETED | FAILED | CONFLICT | REJECTED | FALLBACK

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmarkId": self.benchmark_id,
            "benchmarkName": self.benchmark_name,
            "status": self.status,
            "metrics": self.metrics.to_dict(),
            "expectationResults": self.expectation_results,
            "error": self.error,
            "agentStatus": self.agent_status,
        }


# Thresholds for PASS/PARTIAL/FAIL classification (spec §27).
PASS_STRUCTURAL_THRESHOLD = 0.9      # >= 90% of structural expectations met
PARTIAL_STRUCTURAL_THRESHOLD = 0.5   # >= 50% but < 90% = PARTIAL


def classify_status(expectation_results: dict[str, bool], agent_status: str) -> str:
    """Classify a benchmark run as PASS / PARTIAL / FAIL.

    Rules:
      - If the agent returned REJECTED or CONFLICT → FAIL
      - If the agent returned ERROR → ERROR
      - If >= 90% of expectations met → PASS
      - If >= 50% of expectations met → PARTIAL
      - Otherwise → FAIL
    """
    if agent_status in {"REJECTED", "CONFLICT"}:
        return "FAIL"
    if agent_status == "ERROR":
        return "ERROR"
    if not expectation_results:
        return "FAIL"
    passed = sum(1 for v in expectation_results.values() if v)
    ratio = passed / len(expectation_results)
    if ratio >= PASS_STRUCTURAL_THRESHOLD:
        return "PASS"
    if ratio >= PARTIAL_STRUCTURAL_THRESHOLD:
        return "PARTIAL"
    return "FAIL"


__all__ = [
    "BenchmarkMetrics",
    "BenchmarkResult",
    "classify_status",
    "PASS_STRUCTURAL_THRESHOLD",
    "PARTIAL_STRUCTURAL_THRESHOLD",
]
