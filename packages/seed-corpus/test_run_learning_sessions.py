"""Tests for learning session batch generation (WP-07 Track B-003).

Verifies that 10 failed-to-expert trajectory pairs are generated, each with:
  - A recorded failure (diagnostic + details)
  - A correction (expert trajectory + correction actions)
  - An edit path / insight extracted
  - Verification result (PASS for ≥8 of 10)
  - Provenance tags (source, reviewer, isReal)
  - Diverse archetypes (≥5)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml
from run_learning_sessions import run_learning_sessions


class TestLearningSessionBatch1:
    """WP-07 Track B-003: 10 guided learning sessions."""

    def test_batch_generates_10_sessions(self, tmp_path: Path) -> None:
        """10 sessions are generated and persisted."""
        summary = run_learning_sessions(output_dir=tmp_path)
        assert summary["totalSessions"] == 10
        assert summary["verified"] >= 8  # acceptance: ≥8 of 10 verified
        assert summary["extracted"] >= 8

    def test_sessions_cover_diverse_archetypes(self, tmp_path: Path) -> None:
        """≥ 5 different archetypes covered."""
        summary = run_learning_sessions(output_dir=tmp_path)
        assert len(summary["archetypesCovered"]) >= 5

    def test_sessions_cover_diverse_failure_modes(self, tmp_path: Path) -> None:
        """10 distinct failure modes exercised."""
        summary = run_learning_sessions(output_dir=tmp_path)
        assert len(summary["failureModesCovered"]) == 10

    def test_each_session_has_provenance(self, tmp_path: Path) -> None:
        """Every session has provenance with required fields."""
        run_learning_sessions(output_dir=tmp_path)
        session_files = sorted(Path(tmp_path).glob("session-*.yaml"))
        assert len(session_files) == 10

        for sf in session_files:
            data = yaml.safe_load(sf.read_text())
            assert data["provenance"]["source"] == "learning-session"
            assert data["provenance"]["reviewer"] == "hehenaice"
            assert data["provenance"]["license"] == "Apache-2.0"
            assert data["provenance"]["isReal"] is True
            assert data["provenance"]["failureMode"]
            assert data["provenance"]["archetype"]

    def test_each_session_has_failed_and_expert_trajectories(
        self, tmp_path: Path
    ) -> None:
        """Each session records both a failed and an expert trajectory."""
        run_learning_sessions(output_dir=tmp_path)
        session_files = sorted(Path(tmp_path).glob("session-*.yaml"))

        for sf in session_files:
            data = yaml.safe_load(sf.read_text())
            assert data[
                "failed_trajectory_id"
            ], f"missing failed_trajectory_id in {sf.name}"
            assert data[
                "expert_trajectory_id"
            ], f"missing expert_trajectory_id in {sf.name}"
            assert data["failure_diagnostic"]
            assert data["failure_details"]
            assert len(data["correction_actions"]) >= 1

    def test_each_session_has_insight_id(self, tmp_path: Path) -> None:
        """Each session produced a correction insight."""
        run_learning_sessions(output_dir=tmp_path)
        session_files = sorted(Path(tmp_path).glob("session-*.yaml"))

        for sf in session_files:
            data = yaml.safe_load(sf.read_text())
            assert data["insight_id"], f"missing insight_id in {sf.name}"

    def test_sessions_use_correct_status(self, tmp_path: Path) -> None:
        """Verified sessions have status=VERIFIED."""
        run_learning_sessions(output_dir=tmp_path)
        session_files = sorted(Path(tmp_path).glob("session-*.yaml"))

        verified_count = 0
        for sf in session_files:
            data = yaml.safe_load(sf.read_text())
            if data["status"] == "VERIFIED":
                verified_count += 1
        assert verified_count >= 8  # acceptance: ≥8 of 10 verified

    def test_correction_actions_use_typed_format(self, tmp_path: Path) -> None:
        """Correction actions are typed (tool + args + normalized tuple)."""
        run_learning_sessions(output_dir=tmp_path)
        session_files = sorted(Path(tmp_path).glob("session-*.yaml"))

        for sf in session_files:
            data = yaml.safe_load(sf.read_text())
            for action in data["correction_actions"]:
                assert "tool" in action
                assert "args" in action
                assert "normalized" in action
                assert isinstance(action["normalized"], list)
                assert len(action["normalized"]) >= 1
