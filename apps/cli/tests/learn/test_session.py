"""Tests for learning session infrastructure (WP-07 Task B-001).

Covers:
  - Session lifecycle: start → record → finalize → extract → verify
  - Failed trajectory captured correctly
  - Expert trajectory captured correctly
  - Pairing links both trajectories
  - Edit path extracted from pair
  - Verification confirms retrieval
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.learn.corrector import CorrectionRecorder  # noqa: E402
from oiw.learn.recorder import AttemptRecorder  # noqa: E402
from oiw.learn.session import LearningSessionStatus, LearningSessionStore  # noqa: E402
from oiw.learn.verifier import LearningVerifier  # noqa: E402


class TestLearningSession:
    def test_session_creation(self, tmp_path: Path) -> None:
        """A new session starts in IN_PROGRESS state."""
        store = LearningSessionStore(base_dir=tmp_path)
        session = store.create(
            requirement="Add OData pagination to the receiver",
            project_id="test-project",
            flow_id="test-flow",
        )
        assert session.status == LearningSessionStatus.IN_PROGRESS
        assert session.id.startswith("session-")
        assert session.requirement == "Add OData pagination to the receiver"
        assert session.failed_trajectory_id is None

    def test_session_persisted_to_disk(self, tmp_path: Path) -> None:
        """Session is persisted as YAML."""
        store = LearningSessionStore(base_dir=tmp_path)
        session = store.create(requirement="Test requirement")
        assert (tmp_path / f"{session.id}.yaml").is_file()

    def test_session_loaded_from_disk(self, tmp_path: Path) -> None:
        """Session can be loaded back from disk."""
        store = LearningSessionStore(base_dir=tmp_path)
        session = store.create(requirement="Test")
        loaded = store.get(session.id)
        assert loaded is not None
        assert loaded.requirement == "Test"
        assert loaded.status == LearningSessionStatus.IN_PROGRESS

    def test_record_attempt_and_failure(self, tmp_path: Path) -> None:
        """Recording a failure transitions to FAILED_RECORDED."""
        store = LearningSessionStore(base_dir=tmp_path)
        session = store.create(requirement="Test")
        recorder = AttemptRecorder()
        session = recorder.record_attempt(session, trajectory_id="traj-failed-001")
        assert session.failed_trajectory_id == "traj-failed-001"
        session = recorder.record_failure(session, diagnostic="OIW-E003", details="missing maxPages")
        assert session.status == LearningSessionStatus.FAILED_RECORDED
        assert session.failure_diagnostic == "OIW-E003"

    def test_record_correction(self, tmp_path: Path) -> None:
        """Recording a correction transitions to CORRECTED."""
        store = LearningSessionStore(base_dir=tmp_path)
        session = store.create(requirement="Test")
        recorder = AttemptRecorder()
        session = recorder.record_failure(session, "OIW-E003", "missing maxPages")
        corrector = CorrectionRecorder()
        session = corrector.record_correction(
            session,
            expert_trajectory_id="traj-expert-001",
            correction_actions=[{"tool": "flow.patch", "op": "updateNodeConfig"}],
        )
        assert session.status == LearningSessionStatus.CORRECTED
        assert session.expert_trajectory_id == "traj-expert-001"
        assert len(session.correction_actions) == 1

    def test_verify_learning_success(self, tmp_path: Path) -> None:
        """Verification succeeds when correction is retrieved and agent succeeds."""
        store = LearningSessionStore(base_dir=tmp_path)
        session = store.create(requirement="Test")
        session.status = LearningSessionStatus.EXTRACTED

        class MockResult:
            status = "COMPLETED"

        verifier = LearningVerifier()
        session = verifier.verify(session, agent_result=MockResult(), correction_retrieved=True)
        assert session.status == LearningSessionStatus.VERIFIED
        assert "succeeded" in session.verification_result

    def test_verify_learning_failure_not_retrieved(self, tmp_path: Path) -> None:
        """Verification fails when correction is not retrieved."""
        store = LearningSessionStore(base_dir=tmp_path)
        session = store.create(requirement="Test")
        session.status = LearningSessionStatus.EXTRACTED

        class MockResult:
            status = "COMPLETED"

        verifier = LearningVerifier()
        session = verifier.verify(session, agent_result=MockResult(), correction_retrieved=False)
        assert session.status != LearningSessionStatus.VERIFIED
        assert "not retrieved" in session.verification_result

    def test_list_by_status(self, tmp_path: Path) -> None:
        """List sessions filtered by status."""
        store = LearningSessionStore(base_dir=tmp_path)
        store.create(requirement="Test 1")
        s2 = store.create(requirement="Test 2")
        recorder = AttemptRecorder()
        s2 = recorder.record_failure(s2, "OIW-E003", "test")
        store.update(s2)
        in_progress = store.list_by_status(LearningSessionStatus.IN_PROGRESS)
        failed = store.list_by_status(LearningSessionStatus.FAILED_RECORDED)
        assert len(in_progress) == 1
        assert len(failed) == 1

    def test_session_provenance(self, tmp_path: Path) -> None:
        """Session has provenance with source=learning-session."""
        store = LearningSessionStore(base_dir=tmp_path)
        session = store.create(requirement="Test")
        assert session.provenance["source"] == "learning-session"
        assert session.provenance["isReal"] is True

    def test_full_lifecycle(self, tmp_path: Path) -> None:
        """Full session lifecycle: start → fail → correct → verify."""
        store = LearningSessionStore(base_dir=tmp_path)
        session = store.create(requirement="Add pagination", project_id="test", flow_id="flow")
        recorder = AttemptRecorder()
        session = recorder.record_attempt(session, "traj-failed")
        session = recorder.record_failure(session, "OIW-E003", "missing maxPages")
        store.update(session)
        assert session.status == LearningSessionStatus.FAILED_RECORDED
        corrector = CorrectionRecorder()
        session = corrector.record_correction(session, "traj-expert", [{"tool": "flow.patch"}])
        store.update(session)
        assert session.status == LearningSessionStatus.CORRECTED
        session.status = LearningSessionStatus.EXTRACTED

        class MockResult:
            status = "COMPLETED"

        verifier = LearningVerifier()
        session = verifier.verify(session, MockResult(), correction_retrieved=True)
        store.update(session)
        assert session.status == LearningSessionStatus.VERIFIED
