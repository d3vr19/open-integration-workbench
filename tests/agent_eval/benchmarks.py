"""OIW agent evaluation benchmarks (WP-04 Task 8).

Spec ref: §27 (Benchmark Tasks & Evaluation Metrics).

Each benchmark is a self-contained specification of:
  - A natural-language requirement (the agent's input)
  - The project to apply it to (None = create a new project)
  - The flow ID to target (optional; defaults to the project's only flow)
  - A set of structural expectations the result must satisfy
  - A list of metric probes (test pass rate, validation pass, ...)

Benchmark IDs follow spec §27: bench-001, bench-002, ...

The benchmarks here are intentionally scoped to the *fallback* planner's
capability envelope so they can run in CI without an LLM. Benchmarks
that require LLM reasoning (e.g. multi-step refactor across flows) are
marked `requires_llm=True` and skipped in CI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BenchmarkExpectation:
    """What the agent's result must satisfy for the benchmark to PASS.

    Fields map to spec §27 metric probes:
      - nodes_added: list of node IDs that must appear in the flow after execution
      - nodes_removed: list of node IDs that must NOT appear
      - resources_added: list of resource paths that must exist on disk
      - config_changed: dict of {node_id.config_key: expected_value}
      - flow_created: True if a brand-new flow should exist
      - has_error_handling: True if the flow must have an error subprocess
      - validation_passes: True if `oiw validate --strict` must return 0 errors
      - tests_pass: True if all tests must pass after execution
      - tests_added: int, number of new FlowTest YAMLs expected
    """

    nodes_added: list[str] = field(default_factory=list)
    nodes_removed: list[str] = field(default_factory=list)
    resources_added: list[str] = field(default_factory=list)
    config_changed: dict[str, Any] = field(default_factory=dict)
    flow_created: bool = False
    has_error_handling: bool = False
    validation_passes: bool = True
    tests_pass: bool = True
    tests_added: int = 0


@dataclass
class Benchmark:
    """A single agent evaluation benchmark (spec §27)."""

    id: str  # bench-001, bench-002, ...
    name: str  # short human-readable name
    requirement: str  # natural-language input to the agent
    project: str | None  # examples/order-to-s4, or None to create new
    flow_id: str | None = None  # target flow; None = pick project's only flow
    expected: BenchmarkExpectation = field(default_factory=BenchmarkExpectation)
    requires_llm: bool = False  # True = skipped in CI (fallback can't satisfy)
    tags: list[str] = field(default_factory=list)
    description: str = ""  # longer context for the benchmark


# ---------------------------------------------------------------------------
# Benchmark catalogue (spec §27)
# ---------------------------------------------------------------------------


BENCHMARKS: list[Benchmark] = [
    Benchmark(
        id="bench-001",
        name="Add schema validation",
        requirement="Add JSON schema validation before the normalize step in order-to-s4",
        project="examples/order-to-s4",
        flow_id="order-to-s4",
        expected=BenchmarkExpectation(
            nodes_added=["validate-input"],
            resources_added=["flows/order-to-s4/resources/schemas/input.schema.json"],
            validation_passes=False,  # fallback planner's schema path is intentionally imperfect
            tests_pass=True,
        ),
        tags=["modify-flow", "validation", "fast"],
        description=(
            "The agent must add a validator.json-schema node and a JSON Schema "
            "resource file. The fallback planner's hardcoded plan does this; "
            "the LLM planner should produce a more precise schema (one that "
            "actually validates the order payload, not just `required: [id]`)."
        ),
    ),
    Benchmark(
        id="bench-002",
        name="Create REST-to-HTTP flow",
        requirement="Create a flow that receives JSON orders via HTTPS and forwards them as SOAP to an ERP system",
        project=None,  # creates new project
        flow_id=None,
        expected=BenchmarkExpectation(
            flow_created=True,
            nodes_added=["sender-http", "receiver-http"],
            has_error_handling=True,
            validation_passes=False,  # fallback planner's create-flow plan is minimal
        ),
        tags=["create-flow", "slow"],
        requires_llm=False,  # fallback can produce the skeleton; LLM should refine it
        description=(
            "The agent must create a brand-new flow with an HTTPS sender and "
            "an HTTP receiver (SOAP-via-HTTP in MVP). The fallback planner "
            "produces a minimal skeleton; the LLM planner should add error "
            "handling and a transform step."
        ),
    ),
    Benchmark(
        id="bench-003",
        name="Fix receiver timeout",
        requirement="The S/4HANA receiver times out. Increase the timeout to 60 seconds.",
        project="examples/order-to-s4",
        flow_id="order-to-s4",
        expected=BenchmarkExpectation(
            config_changed={"receiver-s4-eu.timeoutSeconds": 60},
            validation_passes=True,
            tests_pass=True,
        ),
        tags=["fix-flow", "config-change", "fast"],
        description=(
            "The agent must update the receiver-s4-eu node's timeoutSeconds "
            "config from 30 to 60. This is a config-only change — no new nodes. "
            "The fallback planner does NOT currently handle fix-flow intents "
            "well (it returns an empty plan), so this benchmark serves as a "
            "regression test: when LLM is wired in, it must produce a "
            "single updateNodeConfig operation."
        ),
    ),
    # The following benchmarks are sketched but marked requires_llm=True
    # because the fallback planner cannot satisfy them. They are skipped
    # in CI and run only in the nightly LLM benchmark suite.
    Benchmark(
        id="bench-004",
        name="Add error handling subprocess",
        requirement="Add a default exception subprocess to order-to-s4 that logs the error and returns a 500 response",
        project="examples/order-to-s4",
        flow_id="order-to-s4",
        expected=BenchmarkExpectation(
            nodes_added=["error-handler", "log-error"],
            has_error_handling=True,
            validation_passes=True,
        ),
        tags=["modify-flow", "error-handling"],
        requires_llm=True,
        description="Requires LLM reasoning about exception subprocess structure.",
    ),
    Benchmark(
        id="bench-005",
        name="Refactor: extract common transform",
        requirement="Both order-to-s4 flows share a similar normalize step. Extract it into a shared Groovy script resource and reference it from both flows.",
        project="examples/order-to-s4",
        flow_id=None,
        expected=BenchmarkExpectation(
            resources_added=["flows/order-to-s4/resources/scripts/normalize.groovy"],
            validation_passes=True,
            tests_pass=True,
        ),
        tags=["refactor", "cross-flow"],
        requires_llm=True,
        description="Requires LLM reasoning across multiple flows.",
    ),
]


def get_benchmark(bench_id: str) -> Benchmark:
    """Look up a benchmark by ID. Raises KeyError if not found."""
    for b in BENCHMARKS:
        if b.id == bench_id:
            return b
    raise KeyError(f"benchmark not found: {bench_id}")


def fast_benchmarks() -> list[Benchmark]:
    """Return the benchmarks that should run in CI (no LLM required, fast)."""
    return [b for b in BENCHMARKS if not b.requires_llm and "fast" in b.tags]


def ci_benchmarks() -> list[Benchmark]:
    """Return the first 3 benchmarks (bench-001 through bench-003) for CI.

    Per WP-04 Task 8: 'CI integration: Add a agent-eval job to the CI
    workflow that runs benchmarks 001-003 (the fast ones) with a mock
    gateway.'
    """
    return [b for b in BENCHMARKS if b.id in {"bench-001", "bench-002", "bench-003"}]


__all__ = [
    "BENCHMARKS",
    "Benchmark",
    "BenchmarkExpectation",
    "ci_benchmarks",
    "fast_benchmarks",
    "get_benchmark",
]
