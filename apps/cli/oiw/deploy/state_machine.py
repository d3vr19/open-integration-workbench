"""Deployment state machine (WP-05 Task 3).

Spec ref: §18.5 (Deployment State Machine).

States: DRAFT → VALIDATED → TESTED → BUILT → PROPOSED → APPROVED →
         UPLOADED → DEPLOYED → VERIFIED
         (any state can transition to FAILED; FAILED can retry from
         VALIDATED or PROPOSED)

Every transition is validated against ALLOWED_TRANSITIONS, recorded
with evidence (test results, build digest, approver, etc.), and
persisted to .oiw/deployments/{profile}.json.

The state machine is the gatekeeper: no deployment can skip states
(e.g., DRAFT → DEPLOYED is illegal). This enforces the spec §22 Phase 4
exit criterion: "A reviewed Git commit can be deployed to a development
tenant" — the review happens at the PROPOSED → APPROVED transition.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class DeploymentState(StrEnum):
    """Deployment lifecycle states (spec §18.5)."""

    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    TESTED = "TESTED"
    BUILT = "BUILT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    UPLOADED = "UPLOADED"
    DEPLOYED = "DEPLOYED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


# Allowed forward transitions (spec §18.5).
ALLOWED_TRANSITIONS: dict[DeploymentState, list[DeploymentState]] = {
    DeploymentState.DRAFT: [DeploymentState.VALIDATED, DeploymentState.FAILED],
    DeploymentState.VALIDATED: [DeploymentState.TESTED, DeploymentState.FAILED],
    DeploymentState.TESTED: [DeploymentState.BUILT, DeploymentState.FAILED],
    DeploymentState.BUILT: [DeploymentState.PROPOSED, DeploymentState.FAILED],
    DeploymentState.PROPOSED: [DeploymentState.APPROVED, DeploymentState.FAILED],
    DeploymentState.APPROVED: [DeploymentState.UPLOADED, DeploymentState.FAILED],
    DeploymentState.UPLOADED: [DeploymentState.DEPLOYED, DeploymentState.FAILED],
    DeploymentState.DEPLOYED: [DeploymentState.VERIFIED, DeploymentState.FAILED],
    DeploymentState.VERIFIED: [],
    DeploymentState.FAILED: [DeploymentState.VALIDATED, DeploymentState.PROPOSED],
}


@dataclass
class TransitionRecord:
    """Evidence for a single state transition."""

    from_state: str
    to_state: str
    timestamp: str  # ISO 8601
    actor: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeploymentStateRecord:
    """The full state record persisted to disk."""

    current: str = DeploymentState.DRAFT.value
    history: list[dict[str, Any]] = field(default_factory=list)
    package_id: str | None = None
    profile_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, from_state: DeploymentState, to_state: DeploymentState):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"invalid deployment transition: {from_state.value} → {to_state.value}. "
            f"Allowed: {[s.value for s in ALLOWED_TRANSITIONS.get(from_state, [])]}"
        )


@dataclass
class DeploymentEvent:
    """A request to transition the deployment to a new state."""

    target: DeploymentState
    actor: str = "system"
    evidence: dict[str, Any] = field(default_factory=dict)


class DeploymentStateMachine:
    """Manages deployment state transitions for a project + profile.

    State is persisted to `{project}/.oiw/deployments/{profile}.json`
    so it survives across CLI invocations and process restarts.
    """

    def __init__(self, project_path: Path | str, profile_name: str, package_id: str | None = None):
        self.project_path = Path(project_path)
        self.profile_name = profile_name
        self.package_id = package_id
        self.state_file = self.project_path / ".oiw" / "deployments" / f"{profile_name}.json"
        self.state = self._load_or_init()

    def _load_or_init(self) -> DeploymentStateRecord:
        """Load state from disk, or initialize a fresh DRAFT record."""
        if self.state_file.is_file():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                return DeploymentStateRecord(
                    current=data.get("current", DeploymentState.DRAFT.value),
                    history=data.get("history", []),
                    package_id=data.get("package_id"),
                    profile_name=data.get("profile_name", self.profile_name),
                )
            except (json.JSONDecodeError, KeyError):
                pass
        return DeploymentStateRecord(
            current=DeploymentState.DRAFT.value,
            package_id=self.package_id,
            profile_name=self.profile_name,
        )

    def transition(self, event: DeploymentEvent) -> DeploymentState:
        """Validate and apply a state transition.

        Args:
            event: The transition request (target state + actor + evidence).

        Returns:
            The new current state.

        Raises:
            InvalidTransitionError: if the transition is not allowed.
        """
        current = DeploymentState(self.state.current)
        target = event.target
        allowed = ALLOWED_TRANSITIONS.get(current, [])
        if target not in allowed:
            raise InvalidTransitionError(current, target)

        record = TransitionRecord(
            from_state=current.value,
            to_state=target.value,
            timestamp=datetime.now(tz=UTC).isoformat(),
            actor=event.actor,
            evidence=event.evidence,
        )
        self.state.current = target.value
        self.state.history.append(record.to_dict())
        self._persist()
        return target

    @property
    def current_state(self) -> DeploymentState:
        return DeploymentState(self.state.current)

    def is_approved(self) -> bool:
        """Check if the deployment has been approved (or is past approval)."""
        approval_states = {
            DeploymentState.APPROVED,
            DeploymentState.UPLOADED,
            DeploymentState.DEPLOYED,
            DeploymentState.VERIFIED,
        }
        return self.current_state in approval_states

    def is_terminal(self) -> bool:
        """Check if the deployment is in a terminal state (VERIFIED or FAILED)."""
        return self.current_state in {DeploymentState.VERIFIED, DeploymentState.FAILED}

    def get_history(self) -> list[TransitionRecord]:
        """Return the full transition history."""
        return [TransitionRecord(**h) for h in self.state.history]

    def _persist(self) -> None:
        """Persist state to disk."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(self.state.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def reset(self) -> None:
        """Reset to DRAFT state (for testing). Clears history."""
        self.state = DeploymentStateRecord(
            current=DeploymentState.DRAFT.value,
            package_id=self.package_id,
            profile_name=self.profile_name,
        )
        self._persist()


__all__ = [
    "DeploymentState",
    "DeploymentEvent",
    "DeploymentStateMachine",
    "DeploymentStateRecord",
    "TransitionRecord",
    "InvalidTransitionError",
    "ALLOWED_TRANSITIONS",
]
