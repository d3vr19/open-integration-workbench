"""Tests for LLM before/after benchmark (WP-07 D-001 LLM benchmarks).

These tests run bench-004 and bench-005 against the z-ai LLM planner
in both baseline and with-EMG modes. They are SLOW (each benchmark
takes 10-30 seconds due to LLM calls) and are skipped in CI unless
the ZAI_LLM_BENCH=1 environment variable is set.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "seed-corpus"))

from tests.agent_eval.llm_before_after import run_llm_before_after  # noqa: E402

# Skip all tests in this module unless ZAI_LLM_BENCH=1 is set.
# This prevents CI from making live LLM calls (which are slow + cost tokens).
pytestmark = pytest.mark.skipif(
    os.environ.get("ZAI_LLM_BENCH") != "1",
    reason="Set ZAI_LLM_BENCH=1 to run LLM-backed benchmark tests (slow, requires z-ai CLI)",
)


@pytest.fixture(scope="module")
def llm_report() -> dict:
    """Run the LLM before/after once per module."""
    return run_llm_before_after()


class TestLlmBeforeAfter:
    def test_runs_both_benchmarks(self, llm_report: dict) -> None:
        """Both bench-004 and bench-005 ran."""
        assert llm_report["totalBenchmarks"] == 2
        ids = [c["benchmarkId"] for c in llm_report["comparisons"]]
        assert ids == ["bench-004", "bench-005"]

    def test_both_show_emg_activity(self, llm_report: dict) -> None:
        """Acceptance: both benchmarks show EMG activity (avoid warnings)."""
        assert llm_report["improved"] == 2
        assert llm_report["acceptance"]["bothBenchmarksShowEmgActivity"] is True

    def test_no_degradation(self, llm_report: dict) -> None:
        """Acceptance: no benchmark shows degradation with EMG."""
        assert llm_report["degraded"] == 0
        assert llm_report["acceptance"]["noDegradation"] is True

    def test_each_emg_run_surfaces_avoid_warnings(self, llm_report: dict) -> None:
        """Each with-EMG run surfaces ≥ 1 avoid warning."""
        for c in llm_report["comparisons"]:
            assert (
                c["withEmg"]["avoidWarnings"] > 0
            ), f"{c['benchmarkId']} had no avoid warnings"

    def test_report_saved_to_yaml(self, tmp_path: Path) -> None:
        """The report saves as valid YAML."""
        out = tmp_path / "llm-report.yaml"
        run_llm_before_after(output_path=out)
        assert out.is_file()
        doc = yaml.safe_load(out.read_text())
        assert doc["suite"] == "llm-before-after-wp07"
        assert len(doc["comparisons"]) == 2
