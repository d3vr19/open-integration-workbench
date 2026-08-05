"""Tests for C-004 agent-plan incorporation (WP-07 Track C-004 completion)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "seed-corpus"))

from tests.agent_eval.c004_plan_incorporation import (  # noqa: E402
    TEST_REQUIREMENTS,
    run_c004_check,
)


@pytest.fixture(scope="module")
def c004_report() -> dict:
    """Run C-004 once per module (slow — 10 agent runs)."""
    return run_c004_check()


class TestC004AgentPlanIncorporation:
    def test_runs_against_5_requirements(self, c004_report: dict) -> None:
        """C-004 runs against 5 test requirements."""
        report = c004_report["report"]
        assert report["totalRequirements"] == 5

    def test_at_least_5_with_emg_activity(self, c004_report: dict) -> None:
        """Acceptance: ≥ 5 requirements with EMG activity (avoid warnings or insight)."""
        report = c004_report["report"]
        assert (
            report["requirementsWithEmgActivity"] >= 5
        ), f"only {report['requirementsWithEmgActivity']} with EMG activity"
        assert report["acceptance"]["atLeast5WithInsights"] is True

    def test_plans_incorporate_patterns(self, c004_report: dict) -> None:
        """Acceptance: agent plans incorporate retrieved patterns."""
        report = c004_report["report"]
        assert (
            report["requirementsImproved"] >= 5
        ), f"only {report['requirementsImproved']} improved"
        assert report["acceptance"]["plansIncorporatePatterns"] is True

    def test_baseline_comparison_shows_improvement(self, c004_report: dict) -> None:
        """Acceptance: baseline comparison shows improvement."""
        report = c004_report["report"]
        assert report["acceptance"]["baselineComparisonShowsImprovement"] is True
        # The with-EMG runs should have MORE warnings than baseline (because
        # they surface avoid warnings the baseline doesn't)
        assert report["emgTotalWarnings"] > report["baselineTotalWarnings"], (
            f"EMG run ({report['emgTotalWarnings']} warnings) should have more "
            f"than baseline ({report['baselineTotalWarnings']} warnings)"
        )

    def test_each_emg_run_surfaces_avoid_warnings(self, c004_report: dict) -> None:
        """Each with-EMG run surfaces ≥ 1 avoid warning."""
        report = c004_report["report"]
        for r in report["results"]:
            assert (
                r["avoidWarningsInEmgRun"] > 0
            ), f"{r['requirementId']} had no avoid warnings in EMG run"

    def test_test_requirements_cover_diverse_archetypes(self) -> None:
        """TEST_REQUIREMENTS covers ≥ 5 different archetypes."""
        archetypes = {r["archetype"] for r in TEST_REQUIREMENTS}
        assert len(archetypes) >= 5

    def test_end_to_end_passes_acceptance(self, c004_report: dict) -> None:
        """End-to-end: run_c004_check returns passed=True."""
        assert c004_report["passed"] is True

    def test_report_saved_to_yaml(self, tmp_path: Path) -> None:
        """The report saves as valid YAML."""
        out = tmp_path / "c004.yaml"
        run_c004_check(output_path=out)
        assert out.is_file()
        doc = yaml.safe_load(out.read_text())
        assert doc["kind"] == "C004AgentPlanIncorporationReport"
        assert doc["spec"]["totalRequirements"] == 5
