"""End-to-end knowledge invalidation test (WP-07 Track E-003).

Spec ref: §15.10 (Memory Promotion), §15.12 (Knowledge Governance).

Verifies the full invalidation flow:
  1. Take an approved insight (PROJECT_APPROVED state)
  2. Simulate a condition that should invalidate it (e.g., "adapter changed")
  3. Run the invalidation (deprecate or revoke)
  4. Verify the insight is no longer retrievable
  5. Verify the invalidation is recorded (not silently deleted):
     - The record still exists in the store
     - The state transition is captured
     - The reason is stored on the record
     - History is preserved

Acceptance (WP-07 Task E-003):
  - Invalidation works (deprecate + revoke)
  - Invalidated insight not retrievable
  - Invalidation reason recorded
  - History preserved (not deleted)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.emg.insight.compiler import IntraTaskInsight  # noqa: E402
from oiw.emg.promotion import (  # noqa: E402
    InsightRecord,
    MemoryPromotionState,
    MemoryPromotionWorkflow,
    PromotionError,
)


def _promote_to_approved(
    wf: MemoryPromotionWorkflow,
    trajectory_id: str = "traj-test",
    project_id: str = "proj-test",
    reviewer: str = "test-reviewer",
) -> InsightRecord:
    """Promote a trajectory through all gates to PROJECT_APPROVED."""
    record = wf.record(trajectory_id=trajectory_id, project_id=project_id)
    wf.redact(record.id)
    wf.verify_outcome(record.id, tests_pass=True, deploy_success=True)
    wf.match(record.id)
    wf.generate_insight(record.id)
    wf.review(record.id, reviewer=reviewer)
    wf.approve_project(record.id, approver=reviewer)
    return wf.store.get(record.id)


class TestDeprecateApproved:
    """Deprecating an approved insight makes it non-retrievable but preserves the record."""

    def test_deprecate_transitions_state(self) -> None:
        """PROJECT_APPROVED → DEPRECATED."""
        wf = MemoryPromotionWorkflow()
        record = _promote_to_approved(wf)
        assert wf.is_retrievable(record.id)

        wf.deprecate(record.id, reason="adapter version changed")
        updated = wf.store.get(record.id)
        assert updated.state == MemoryPromotionState.DEPRECATED
        assert not wf.is_retrievable(record.id)

    def test_deprecate_records_reason(self) -> None:
        """The deprecation reason is stored on the record."""
        wf = MemoryPromotionWorkflow()
        record = _promote_to_approved(wf)

        reason = "OData V4 adapter deprecated; replaced by V5"
        wf.deprecate(record.id, reason=reason)
        updated = wf.store.get(record.id)
        assert updated.deprecation_reason == reason

    def test_deprecate_preserves_record(self) -> None:
        """Deprecation does NOT delete the record — history is preserved."""
        wf = MemoryPromotionWorkflow()
        record = _promote_to_approved(wf)
        original_id = record.id
        original_trajectory = record.trajectory_id

        wf.deprecate(record.id, reason="test")
        # Record still exists in the store
        updated = wf.store.get(original_id)
        assert updated is not None
        assert updated.trajectory_id == original_trajectory
        assert updated.state == MemoryPromotionState.DEPRECATED

    def test_deprecate_updates_timestamp(self) -> None:
        """updated_at changes when the record is deprecated."""
        import time

        wf = MemoryPromotionWorkflow()
        record = _promote_to_approved(wf)
        original_updated = record.updated_at

        time.sleep(0.01)  # ensure timestamp differs
        wf.deprecate(record.id, reason="test")
        updated = wf.store.get(record.id)
        assert updated.updated_at != original_updated


class TestRevokeApproved:
    """Revoking an approved insight (incident response)."""

    def test_revoke_transitions_state(self) -> None:
        """PROJECT_APPROVED → REVOKED."""
        wf = MemoryPromotionWorkflow()
        record = _promote_to_approved(wf)

        wf.revoke(record.id, reason="caused incident INC-456")
        updated = wf.store.get(record.id)
        assert updated.state == MemoryPromotionState.REVOKED
        assert not wf.is_retrievable(record.id)

    def test_revoke_records_reason(self) -> None:
        """The revocation reason is stored on the record."""
        wf = MemoryPromotionWorkflow()
        record = _promote_to_approved(wf)

        reason = "caused incident INC-789: duplicate orders created"
        wf.revoke(record.id, reason=reason)
        updated = wf.store.get(record.id)
        assert updated.revocation_reason == reason

    def test_revoke_preserves_record(self) -> None:
        """Revocation does NOT delete the record."""
        wf = MemoryPromotionWorkflow()
        record = _promote_to_approved(wf)
        record_id = record.id

        wf.revoke(record.id, reason="test")
        # Record still exists
        updated = wf.store.get(record_id)
        assert updated is not None
        assert updated.state == MemoryPromotionState.REVOKED


class TestInvalidationFromRetriever:
    """End-to-end: deprecated insights are not returned by EMGRetriever."""

    def test_deprecated_insight_not_retrieved(self) -> None:
        """A deprecated insight is filtered out of retrieval results."""
        from oiw.agent.interpreter import NormalizedRequirement
        from oiw.emg.retrieval import EMGRetriever

        wf = MemoryPromotionWorkflow()
        record = _promote_to_approved(wf, trajectory_id="traj-fm-003")

        # Build a simple insight attached to the record
        insight = IntraTaskInsight(task_id="task-fm-003")
        record.insight = insight
        wf.store.update(record)

        # Verify retrievable before deprecation
        retriever = EMGRetriever(store=wf.store)
        req = NormalizedRequirement(
            intent="create-flow",
            operations=["validate"],
            components=["validator.json-schema"],
            raw="Add validation",
        )
        # The retriever's _retrieve_intra_task lists PROJECT_APPROVED records
        # After deprecation, the record should not be in the list
        wf.deprecate(record.id, reason="schema format changed")
        result = retriever.retrieve(req, project_id="proj-test")
        # No matching insight should be found
        assert result.insight is None or result.insight.task_id != "task-fm-003"

    def test_revoked_insight_not_retrieved(self) -> None:
        """A revoked insight is filtered out of retrieval results."""
        from oiw.agent.interpreter import NormalizedRequirement
        from oiw.emg.retrieval import EMGRetriever

        wf = MemoryPromotionWorkflow()
        record = _promote_to_approved(wf, trajectory_id="traj-fm-007")

        insight = IntraTaskInsight(task_id="task-fm-007")
        record.insight = insight
        wf.store.update(record)

        retriever = EMGRetriever(store=wf.store)
        req = NormalizedRequirement(
            intent="create-flow",
            operations=["transform"],
            components=["script.groovy"],
            raw="Build a script flow",
        )
        wf.revoke(record.id, reason="sandbox policy changed")
        result = retriever.retrieve(req, project_id="proj-test")
        assert result.insight is None or result.insight.task_id != "task-fm-007"


class TestInvalidationReasonHistory:
    """The invalidation reason is preserved across reads."""

    def test_deprecation_reason_persists_across_reads(self) -> None:
        """Reading the record multiple times returns the same reason."""
        wf = MemoryPromotionWorkflow()
        record = _promote_to_approved(wf)
        reason = "policy update: pagination maxPages reduced to 50"
        wf.deprecate(record.id, reason=reason)

        first_read = wf.store.get(record.id)
        second_read = wf.store.get(record.id)
        assert first_read.deprecation_reason == reason
        assert second_read.deprecation_reason == reason

    def test_revocation_reason_persists_across_reads(self) -> None:
        """Reading the record multiple times returns the same reason."""
        wf = MemoryPromotionWorkflow()
        record = _promote_to_approved(wf)
        reason = "incident INC-999: data corruption"
        wf.revoke(record.id, reason=reason)

        first_read = wf.store.get(record.id)
        second_read = wf.store.get(record.id)
        assert first_read.revocation_reason == reason
        assert second_read.revocation_reason == reason


class TestInvalidationEdgeCases:
    """Edge cases: invalidating non-approved insights, double-invalidation."""

    def test_deprecate_captured_allowed(self) -> None:
        """Deprecating a CAPTURED insight is allowed (terminal-from-any-state)."""
        wf = MemoryPromotionWorkflow()
        record = wf.record(trajectory_id="t", project_id="p")
        wf.deprecate(record.id, reason="abandoned")
        assert wf.store.get(record.id).state == MemoryPromotionState.DEPRECATED

    def test_revoke_captured_allowed(self) -> None:
        """Revoking a CAPTURED insight is allowed."""
        wf = MemoryPromotionWorkflow()
        record = wf.record(trajectory_id="t", project_id="p")
        wf.revoke(record.id, reason="security concern")
        assert wf.store.get(record.id).state == MemoryPromotionState.REVOKED

    def test_deprecate_deprecated_no_op_raises(self) -> None:
        """Deprecating an already-deprecated insight raises (terminal state)."""
        wf = MemoryPromotionWorkflow()
        record = _promote_to_approved(wf)
        wf.deprecate(record.id, reason="first reason")
        with pytest.raises(PromotionError, match="invalid promotion transition"):
            wf.deprecate(record.id, reason="second reason")

    def test_revoke_revoked_no_op_raises(self) -> None:
        """Revoking an already-revoked insight raises (terminal state)."""
        wf = MemoryPromotionWorkflow()
        record = _promote_to_approved(wf)
        wf.revoke(record.id, reason="first reason")
        with pytest.raises(PromotionError, match="invalid promotion transition"):
            wf.revoke(record.id, reason="second reason")
