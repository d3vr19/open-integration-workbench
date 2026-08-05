"""Tests for before/after benchmark (WP-07 Track D-001)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "mcp-server"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "server-python-prototype"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "seed-corpus"))

from tests.agent_eval.before_after import run_before_after  # noqa: E402


@pytest.fixture(scope="module")
def before_after_report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Run before/after once per module (it's slow — 6 agent runs)."""
    out = tmp_path_factory.mktemp("before-after") / "report.yaml"
    return run_before_after(output_path=out)


class TestBeforeAfterBenchmark:
    def test_runs_all_ci_benchmarks(self, before_after_report: dict) -> None:
        """Before/after runs bench-001 to bench-003 in both modes."""
        report = before_after_report
        assert report["totalBenchmarks"] == 3
        assert len(report["comparisons"]) == 3
        bench_ids = [c["benchmarkId"] for c in report["comparisons"]]
        assert bench_ids == ["bench-001", "bench-002", "bench-003"]

    def test_at_least_two_improved(self, before_after_report: dict) -> None:
        """Acceptance: ≥ 2 benchmarks show measurable improvement with EMG."""
        report = before_after_report
        assert (
            report["improved"] >= 2
        ), f"only {report['improved']} benchmarks improved (need ≥2)"
        assert report["acceptance"]["atLeast2Improved"] is True

    def test_no_degradation(self, before_after_report: dict) -> None:
        """Acceptance: no benchmark shows degradation with EMG."""
        report = before_after_report
        assert report["degraded"] == 0, f"{report['degraded']} benchmarks degraded"
        assert report["acceptance"]["noDegradation"] is True

    def test_emg_run_surfaces_avoid_warnings(self, before_after_report: dict) -> None:
        """The with-EMG run produces OIW-AVOID-* warnings."""
        report = before_after_report
        for c in report["comparisons"]:
            assert (
                c["withEmg"]["avoidWarnings"] > 0
            ), f"{c['benchmarkId']} had no avoid warnings"

    def test_report_yaml_round_trip(
        self, before_after_report: dict, tmp_path: Path
    ) -> None:
        """The report can be written and re-read as YAML."""
        out = tmp_path / "report.yaml"
        out.write_text(
            yaml.safe_dump(
                before_after_report, sort_keys=False, default_flow_style=False
            )
        )
        assert out.is_file()
        doc = yaml.safe_load(out.read_text())
        assert doc["suite"] == "before-after-wp07"
        assert "comparisons" in doc
