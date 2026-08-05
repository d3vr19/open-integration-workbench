"""Tests for learning curve visualization (WP-07 Track D-004)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "seed-corpus"))

from tests.agent_eval.learning_curve import (  # noqa: E402
    _is_monotonic,
    generate_learning_curve,
    run_d004_check,
    save_learning_curve,
)
from run_learning_sessions import run_learning_sessions  # noqa: E402


@pytest.fixture(scope="module")
def sessions_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate 30 sessions once for all tests."""
    d = tmp_path_factory.mktemp("sessions")
    run_learning_sessions(output_dir=d, batches=(1, 2, 3))
    return d


class TestLearningCurve:
    def test_generates_5_data_points(self, sessions_dir: Path) -> None:
        """Learning curve recorded at 5-session intervals (0, 5, 10, 20, 30)."""
        points = generate_learning_curve(sessions_dir)
        assert len(points) == 5
        session_counts = [p.sessions for p in points]
        assert session_counts == [0, 5, 10, 20, 30]

    def test_monotonic_improvement(self, sessions_dir: Path) -> None:
        """Acceptance: monotonic improvement in benchmark pass rate."""
        points = generate_learning_curve(sessions_dir)
        assert _is_monotonic(
            points
        ), f"pass rates not monotonic: {[p.benchmark_pass_rate for p in points]}"

    def test_baseline_has_zero_avoid_warnings(self, sessions_dir: Path) -> None:
        """At 0 sessions, no avoid warnings are surfaced."""
        points = generate_learning_curve(sessions_dir)
        assert points[0].sessions == 0
        assert points[0].avoid_warnings_surfaced == 0

    def test_avoid_warnings_grow_with_sessions(self, sessions_dir: Path) -> None:
        """More sessions → more avoid warnings surfaced."""
        points = generate_learning_curve(sessions_dir)
        avoid_counts = [p.avoid_warnings_surfaced for p in points]
        # Monotonic non-decreasing
        for i in range(1, len(avoid_counts)):
            assert (
                avoid_counts[i] >= avoid_counts[i - 1]
            ), f"avoid warnings decreased at point {i}: {avoid_counts}"

    def test_pass_rate_at_30_sessions_is_high(self, sessions_dir: Path) -> None:
        """At 30 sessions, pass rate should be ≥ 0.9."""
        points = generate_learning_curve(sessions_dir)
        last = points[-1]
        assert last.sessions == 30
        assert last.benchmark_pass_rate >= 0.9

    def test_save_yaml(self, sessions_dir: Path, tmp_path: Path) -> None:
        """The curve saves as valid YAML."""
        points = generate_learning_curve(sessions_dir)
        out = save_learning_curve(points, tmp_path / "curve.yaml")
        assert out.is_file()
        doc = yaml.safe_load(out.read_text())
        assert doc["kind"] == "LearningCurve"
        assert len(doc["spec"]["learningCurve"]) == 5
        assert doc["spec"]["monotonicImprovement"] is True

    def test_run_d004_check_passes(self, sessions_dir: Path, tmp_path: Path) -> None:
        """End-to-end: run_d004_check returns passed=True."""
        result = run_d004_check(
            sessions_dir=sessions_dir, output_path=tmp_path / "curve.yaml"
        )
        assert result["passed"] is True
        assert result["monotonicImprovement"] is True
        assert (tmp_path / "curve.yaml").is_file()

    def test_structural_correctness_improves(self, sessions_dir: Path) -> None:
        """Structural correctness at 30 sessions ≥ at 0 sessions."""
        points = generate_learning_curve(sessions_dir)
        assert (
            points[-1].avg_structural_correctness
            >= points[0].avg_structural_correctness
        )
