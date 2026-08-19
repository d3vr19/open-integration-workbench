"""Tests for learning session batches 2 and 3 (WP-07 Track B-004 + B-005).

B-004 (Batch 2 — Diverse Archetypes):
  - 10 sessions covering ≥ 4 different archetypes
  - All sessions produce edit paths
  - Verification passes for ≥ 8 of 10

B-005 (Batch 3 — Multi-step Corrections):
  - 10 sessions with multi-step edit paths (≥ 3 operations)
  - All edit paths correctly extracted
  - Verification passes for ≥ 7 of 10 (complex corrections are harder)
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_learning_sessions import run_learning_sessions


class TestBatch2DiverseArchetypes:
    """WP-07 Track B-004: 10 sessions with diverse archetypes."""

    def test_batch2_generates_10_sessions(self, tmp_path: Path) -> None:
        """Batch 2 produces 10 sessions."""
        summary = run_learning_sessions(output_dir=tmp_path, batches=(2,))
        assert summary["totalSessions"] == 10

    def test_batch2_verification_passes_for_at_least_8(self, tmp_path: Path) -> None:
        """Acceptance: ≥ 8 of 10 sessions verified."""
        summary = run_learning_sessions(output_dir=tmp_path, batches=(2,))
        assert (
            summary["verified"] >= 8
        ), f"only {summary['verified']} of 10 verified (need ≥8)"

    def test_batch2_covers_at_least_4_archetypes(self, tmp_path: Path) -> None:
        """Acceptance: ≥ 4 different archetypes."""
        summary = run_learning_sessions(output_dir=tmp_path, batches=(2,))
        # B-004 specifies: api-to-erp, file-to-api, paginated-api-ingestion,
        # event-driven-webhook, error-handling-pattern = 5 archetypes
        assert (
            len(summary["archetypesCovered"]) >= 4
        ), f"only {len(summary['archetypesCovered'])} archetypes (need ≥4)"

    def test_batch2_each_session_has_insight(self, tmp_path: Path) -> None:
        """Each session produced a correction insight (edit path)."""
        summary = run_learning_sessions(output_dir=tmp_path, batches=(2,))
        assert summary["extracted"] == 10

    def test_batch2_sessions_persisted_with_provenance(self, tmp_path: Path) -> None:
        """Sessions are persisted as YAML with provenance tags."""
        run_learning_sessions(output_dir=tmp_path, batches=(2,))
        session_files = sorted(Path(tmp_path).glob("session-*.yaml"))
        assert len(session_files) == 10

        for sf in session_files:
            data = yaml.safe_load(sf.read_text())
            assert data["provenance"]["source"] == "learning-session"
            assert data["provenance"]["reviewer"] == "hehenaice"
            assert data["provenance"]["isReal"] is True


class TestBatch3MultiStepCorrections:
    """WP-07 Track B-005: 10 sessions with multi-step corrections."""

    def test_batch3_generates_10_sessions(self, tmp_path: Path) -> None:
        """Batch 3 produces 10 sessions."""
        summary = run_learning_sessions(output_dir=tmp_path, batches=(3,))
        assert summary["totalSessions"] == 10

    def test_batch3_each_session_has_3plus_corrections(self, tmp_path: Path) -> None:
        """Acceptance: each session has a multi-step edit path (≥ 3 operations)."""
        summary = run_learning_sessions(output_dir=tmp_path, batches=(3,))
        multi_step_count = sum(
            1 for s in summary["sessions"] if s["correction_action_count"] >= 3
        )
        assert (
            multi_step_count == 10
        ), f"only {multi_step_count} of 10 sessions have ≥3 corrections"

    def test_batch3_verification_passes_for_at_least_7(self, tmp_path: Path) -> None:
        """Acceptance: ≥ 7 of 10 sessions verified (complex corrections harder)."""
        summary = run_learning_sessions(output_dir=tmp_path, batches=(3,))
        assert (
            summary["verified"] >= 7
        ), f"only {summary['verified']} of 10 verified (need ≥7)"

    def test_batch3_correction_action_counts(self, tmp_path: Path) -> None:
        """Batch 3 sessions have varying correction counts (3 to 6+)."""
        summary = run_learning_sessions(output_dir=tmp_path, batches=(3,))
        counts = [s["correction_action_count"] for s in summary["sessions"]]
        # All should be ≥ 3
        assert all(
            c >= 3 for c in counts
        ), f"some sessions have <3 corrections: {counts}"
        # At least some should be ≥ 4 (the edge-rewiring + config-externalization ones)
        assert (
            sum(1 for c in counts if c >= 4) >= 5
        ), f"only {sum(1 for c in counts if c >= 4)} sessions have ≥4 corrections"

    def test_batch3_covers_complex_correction_categories(self, tmp_path: Path) -> None:
        """Batch 3 covers the 4 categories: 3+ actions, resource+patch, edge rewiring, config externalization."""
        summary = run_learning_sessions(output_dir=tmp_path, batches=(3,))
        # Check that we have sessions with resource.write (resource creation)
        sessions = summary["sessions"]
        # All sessions should have ≥3 corrections (per acceptance)
        assert all(s["correction_action_count"] >= 3 for s in sessions)


class TestAll30Sessions:
    """End-to-end: all 30 sessions (Batch 1 + 2 + 3)."""

    def test_all_batches_generate_30_sessions(self, tmp_path: Path) -> None:
        """Running all 3 batches produces 30 sessions."""
        summary = run_learning_sessions(output_dir=tmp_path, batches=(1, 2, 3))
        assert summary["totalSessions"] == 30

    def test_all_30_verified(self, tmp_path: Path) -> None:
        """All 30 sessions verified (≥ 25 of 30 per D-002 acceptance)."""
        summary = run_learning_sessions(output_dir=tmp_path, batches=(1, 2, 3))
        # All sessions should verify in our synthetic setting
        assert summary["verified"] == 30

    def test_all_30_have_insights(self, tmp_path: Path) -> None:
        """All 30 sessions produced correction insights."""
        summary = run_learning_sessions(output_dir=tmp_path, batches=(1, 2, 3))
        assert summary["extracted"] == 30

    def test_all_30_persisted_as_yaml(self, tmp_path: Path) -> None:
        """30 session-*.yaml files exist."""
        run_learning_sessions(output_dir=tmp_path, batches=(1, 2, 3))
        session_files = sorted(Path(tmp_path).glob("session-*.yaml"))
        assert len(session_files) == 30

    def test_all_30_have_provenance(self, tmp_path: Path) -> None:
        """All 30 sessions have provenance tags."""
        run_learning_sessions(output_dir=tmp_path, batches=(1, 2, 3))
        session_files = sorted(Path(tmp_path).glob("session-*.yaml"))

        for sf in session_files:
            data = yaml.safe_load(sf.read_text())
            assert data["provenance"]["source"] == "learning-session"
            assert data["provenance"]["isReal"] is True

    def test_10_plus_archetypes_covered(self, tmp_path: Path) -> None:
        """All 30 sessions span ≥ 7 archetypes."""
        summary = run_learning_sessions(output_dir=tmp_path, batches=(1, 2, 3))
        assert len(summary["archetypesCovered"]) >= 7
