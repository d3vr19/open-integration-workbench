# OIW Agent Evaluation Harness (WP-04 Task 8)

Spec ref: §27 (Benchmark Tasks & Evaluation Metrics).

This directory contains the agent evaluation harness that measures how
well the OIW agent pipeline performs on a fixed set of benchmark tasks.

## Quick Start

```bash
# From repo root, with PYTHONPATH including apps/cli, apps/mcp-server,
# apps/server-python-prototype:
export PYTHONPATH="$PWD/apps/cli:$PWD/apps/mcp-server:$PWD/apps/server-python-prototype:$PWD"

# List all benchmarks
python -m tests.agent_eval.runner --list

# Run the CI suite (bench-001..003 in fallback mode)
python -m tests.agent_eval.runner --output agent-eval-report.yaml

# Run a single benchmark
python -m tests.agent_eval.runner -b bench-001 -o bench-001.yaml
```

## Benchmarks

| ID | Name | Mode | Status (fallback baseline) |
|----|------|------|----------------------------|
| bench-001 | Add schema validation | fallback | PASS (structural=1.0) |
| bench-002 | Create REST-to-HTTP flow | fallback | FAIL (structural=0.2) |
| bench-003 | Fix receiver timeout | fallback | PARTIAL (structural=0.75) |
| bench-004 | Add error handling subprocess | LLM-only | (skipped in CI) |
| bench-005 | Refactor: extract common transform | LLM-only | (skipped in CI) |

The CI suite (`ci_benchmarks()`) runs bench-001..003. The nightly suite
adds bench-004 and bench-005 (requires `OIW_MODEL_GATEWAY_KEY`).

## Metrics (per benchmark)

Each benchmark produces a `BenchmarkMetrics` vector (spec §27):

| Metric | Description |
|--------|-------------|
| `structural_correctness` | Fraction of structural expectations met (0.0–1.0) |
| `test_pass_rate` | Fraction of project tests that pass after execution |
| `policy_violations` | Count of policy rule violations (`oiw validate --strict` errors) |
| `human_corrections` | Always 0 in fallback/CI; nonzero only in human-eval mode |
| `token_cost` | 0 for fallback; from gateway usage for LLM runs |
| `latency_ms` | Wall-clock duration of the agent run |
| `hallucinated_components` | Count of step types NOT in the OIW plugin registry |
| `secret_handling_violations` | Count of unredacted secrets found in trajectory YAML |
| `trajectory_id` | Links to the persisted trajectory file |

## Pass / Partial / Fail Classification

- **PASS**: >= 90% of structural expectations met AND agent status COMPLETED.
- **PARTIAL**: >= 50% but < 90% of expectations met.
- **FAIL**: < 50% of expectations met, OR agent returned REJECTED/CONFLICT.
- **ERROR**: Harness itself failed (exception, missing project, ...).
- **SKIP**: Benchmark skipped (e.g. `requires_llm=True` in CI).

## Regression Gate

The CI workflow (`.github/workflows/agent-eval.yaml`) enforces:
- **bench-001 MUST PASS** in fallback mode. A regression here means the
  fallback planner broke — investigate immediately.
- **bench-002 and bench-003 may FAIL/PARTIAL** in fallback mode. These
  are known limitations of the keyword-based planner; the LLM planner
  is expected to close these gaps. When the LLM planner is wired in,
  these benchmarks should move to PASS.
- **No benchmark may EROR**. An ERROR status means the harness itself
  broke (not the agent).

## Baselines

The `baselines/` directory contains captured metrics from known-good
runs. Compare against these to detect regressions:

- `baseline-fallback-2026-08-02.yaml`: fallback planner baseline.
  bench-001=PASS, bench-002=FAIL, bench-003=PARTIAL.

When the LLM planner is wired in, a new baseline
`baseline-llm-YYYY-MM-DD.yaml` should be captured and the fallback
baselines preserved for comparison.

## Adding a New Benchmark

1. Add a `Benchmark` entry to `BENCHMARKS` in `benchmarks.py`.
2. Set `requires_llm=True` if the fallback planner cannot satisfy it.
3. Add the benchmark ID to `ci_benchmarks()` if it should run in CI
   (currently returns bench-001..003).
4. Add a test in `test_runner.py` that asserts the expected status.
5. Run `python -m tests.agent_eval.runner -b <new-id>` to verify.

## Architecture

```
tests/agent_eval/
├── __init__.py
├── benchmarks.py        # Benchmark + BenchmarkExpectation dataclasses, BENCHMARKS list
├── metrics.py           # BenchmarkMetrics + BenchmarkResult, classify_status()
├── runner.py            # run_benchmark_fallback(), run_ci_suite(), CLI main()
├── test_runner.py       # 19 tests (incl. 2 mandatory WP-04 tests)
└── baselines/           # Captured metrics from known-good runs
    └── baseline-fallback-2026-08-02.yaml
```

The runner is a plain Python module (not pytest) so it can be invoked
from CI as `python -m tests.agent_eval.runner` and produce a YAML report.
The tests in `test_runner.py` cover both the harness itself and the
benchmarks (the mandatory WP-04 tests `test_benchmark_001_with_mock`
and `test_benchmark_001_without_llm` are in there).

## Spec Compliance

- §27 Benchmark Tasks & Evaluation Metrics: ✓ (5 benchmarks, 9 metrics)
- §22 Phase 3 exit criterion "Evaluation results are reproducible": ✓
  (fallback mode is deterministic; same input → same output)
- WP-04 §3 Task 8 acceptance: ✓ (3-5 benchmarks, fallback baseline,
  CI job, metrics collected, 2 harness tests)
