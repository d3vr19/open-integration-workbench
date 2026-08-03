"""Tests for the deployment state machine (WP-05 Task 3).

Covers:
  - Valid forward transitions through happy path
  - Invalid transitions rejected (e.g., DRAFT → DEPLOYED)
  - FAILED allows retry from VALIDATED or PROPOSED
  - Evidence recorded for each transition
  - State persisted to disk, survives restart
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oiw.deploy import (
    DeploymentEvent,
    DeploymentState,
    DeploymentStateMachine,
    InvalidTransitionError,
)


@pytest.fixture()
def sm(tmp_path: Path) -> DeploymentStateMachine:
    """Fresh state machine in a temp project dir."""
    return DeploymentStateMachine(tmp_path, "dev", package_id="order-to-s4")


def test_happy_path_forward_transitions(sm: DeploymentStateMachine) -> None:
    """DRAFT → VALIDATED → TESTED → BUILT → PROPOSED → APPROVED →
    UPLOADED → DEPLOYED → VERIFIED."""
    transitions = [
        DeploymentState.VALIDATED,
        DeploymentState.TESTED,
        DeploymentState.BUILT,
        DeploymentState.PROPOSED,
        DeploymentState.APPROVED,
        DeploymentState.UPLOADED,
        DeploymentState.DEPLOYED,
        DeploymentState.VERIFIED,
    ]
    for target in transitions:
        result = sm.transition(DeploymentEvent(target=target, actor="test"))
        assert result == target
    assert sm.current_state == DeploymentState.VERIFIED
    assert sm.is_terminal()


def test_invalid_transition_rejected(sm: DeploymentStateMachine) -> None:
    """DRAFT → DEPLOYED is illegal (skips states)."""
    with pytest.raises(InvalidTransitionError) as exc_info:
        sm.transition(DeploymentEvent(target=DeploymentState.DEPLOYED))
    assert "DRAFT" in str(exc_info.value)
    assert "DEPLOYED" in str(exc_info.value)


def test_any_state_can_fail(sm: DeploymentStateMachine) -> None:
    """Any state can transition to FAILED."""
    sm.transition(DeploymentEvent(target=DeploymentState.VALIDATED))
    sm.transition(DeploymentEvent(target=DeploymentState.FAILED, evidence={"error": "test"}))
    assert sm.current_state == DeploymentState.FAILED


def test_failed_can_retry_from_validated(sm: DeploymentStateMachine) -> None:
    """FAILED → VALIDATED is allowed (retry from last good state)."""
    sm.transition(DeploymentEvent(target=DeploymentState.VALIDATED))
    sm.transition(DeploymentEvent(target=DeploymentState.FAILED))
    sm.transition(DeploymentEvent(target=DeploymentState.VALIDATED))
    assert sm.current_state == DeploymentState.VALIDATED


def test_failed_can_retry_from_proposed(sm: DeploymentStateMachine) -> None:
    """FAILED → PROPOSED is allowed (retry from last good state)."""
    sm.transition(DeploymentEvent(target=DeploymentState.VALIDATED))
    sm.transition(DeploymentEvent(target=DeploymentState.TESTED))
    sm.transition(DeploymentEvent(target=DeploymentState.BUILT))
    sm.transition(DeploymentEvent(target=DeploymentState.PROPOSED))
    sm.transition(DeploymentEvent(target=DeploymentState.FAILED))
    sm.transition(DeploymentEvent(target=DeploymentState.PROPOSED))
    assert sm.current_state == DeploymentState.PROPOSED


def test_evidence_recorded(sm: DeploymentStateMachine) -> None:
    """Each transition records evidence + actor + timestamp."""
    sm.transition(
        DeploymentEvent(
            target=DeploymentState.VALIDATED,
            actor="alice",
            evidence={"testResults": "5/5 passed"},
        )
    )
    history = sm.get_history()
    assert len(history) == 1
    record = history[0]
    assert record.from_state == "DRAFT"
    assert record.to_state == "VALIDATED"
    assert record.actor == "alice"
    assert record.evidence["testResults"] == "5/5 passed"
    assert record.timestamp  # non-empty ISO string


def test_state_persisted_to_disk(tmp_path: Path) -> None:
    """State survives restart — load from the same file."""
    sm1 = DeploymentStateMachine(tmp_path, "dev", "pkg")
    sm1.transition(DeploymentEvent(target=DeploymentState.VALIDATED))
    assert (tmp_path / ".oiw" / "deployments" / "dev.json").is_file()

    # New instance, same project path — should load persisted state
    sm2 = DeploymentStateMachine(tmp_path, "dev", "pkg")
    assert sm2.current_state == DeploymentState.VALIDATED
    assert len(sm2.get_history()) == 1


def test_is_approved(sm: DeploymentStateMachine) -> None:
    """is_approved() returns True for APPROVED and later states."""
    assert not sm.is_approved()
    sm.transition(DeploymentEvent(target=DeploymentState.VALIDATED))
    sm.transition(DeploymentEvent(target=DeploymentState.TESTED))
    sm.transition(DeploymentEvent(target=DeploymentState.BUILT))
    sm.transition(DeploymentEvent(target=DeploymentState.PROPOSED))
    assert not sm.is_approved()
    sm.transition(DeploymentEvent(target=DeploymentState.APPROVED))
    assert sm.is_approved()
