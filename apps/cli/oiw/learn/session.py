"""Learning session dataclass + lifecycle management (WP-07 Task B-001).

Spec ref: §15.7 (Expert Trajectory Eligibility), §15.8 (Reward Vector).

A LearningSession captures the full cycle:
  1. Agent attempts a task → fails
  2. Human corrects the failure → expert trajectory
  3. Graph matching extracts the edit path
  4. Correction insight is stored in the EMG
  5. Verification: re-run the task, confirm the correction is retrieved

Sessions are persisted to packages/seed-corpus/learning-sessions/{id}.yaml.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class LearningSessionStatus(str, Enum):
    """Lifecycle states for a learning session."""

    IN_PROGRESS = "IN_PROGRESS"
    FAILED_RECORDED = "FAILED_RECORDED"
    CORRECTED = "CORRECTED"
    PAIRED = "PAIRED"
    EXTRACTED = "EXTRACTED"
    VERIFIED = "VERIFIED"


@dataclass
class LearningSession:
    """A structured learning session producing a failed-to-expert pair.

    Attributes:
        id: Unique session ID (e.g., "session-fm-001-1")
        requirement: Natural-language requirement
        normalized_requirement: Structured interpretation (intent, ops, components)
        project_id: Project the session runs against
        flow_id: Target flow
        status: Current lifecycle state
        failed_trajectory_id: ID of the failed agent trajectory
        failure_diagnostic: Diagnostic code (e.g., "OIW-E003")
        failure_details: Human-readable description of what went wrong
        expert_trajectory_id: ID of the corrected expert trajectory
        correction_actions: What the expert did differently (typed actions)
        edit_path_id: ID of the extracted graph edit path
        insight_id: ID of the stored correction insight
        verification_result: Result of the verification step
        provenance: Source metadata (source, reviewer, license, isReal)
        created_at: Session start timestamp
        completed_at: Session completion timestamp
    """

    id: str
    requirement: str
    normalized_requirement: dict[str, Any] = field(default_factory=dict)
    project_id: str = ""
    flow_id: str = ""
    status: LearningSessionStatus = LearningSessionStatus.IN_PROGRESS

    # Failed attempt
    failed_trajectory_id: str | None = None
    failure_diagnostic: str | None = None
    failure_details: str | None = None

    # Expert correction
    expert_trajectory_id: str | None = None
    correction_actions: list[dict[str, Any]] = field(default_factory=list)

    # Extracted knowledge
    edit_path_id: str | None = None
    insight_id: str | None = None

    # Verification
    verification_result: str | None = None

    # Provenance
    provenance: dict[str, Any] = field(
        default_factory=lambda: {
            "source": "learning-session",
            "reviewer": "",
            "license": "Apache-2.0",
            "isReal": True,
        }
    )

    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, default_flow_style=False, allow_unicode=True)


class LearningSessionStore:
    """Persists learning sessions to disk.

    Sessions are stored at {base_dir}/{session_id}.yaml.
    """

    def __init__(self, base_dir: Path | str = "packages/seed-corpus/learning-sessions"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        requirement: str,
        project_id: str = "",
        flow_id: str = "",
        normalized_requirement: dict[str, Any] | None = None,
    ) -> LearningSession:
        """Create a new learning session and persist it."""
        session = LearningSession(
            id=f"session-{uuid.uuid4().hex[:12]}",
            requirement=requirement,
            project_id=project_id,
            flow_id=flow_id,
            normalized_requirement=normalized_requirement or {},
        )
        self._persist(session)
        return session

    def get(self, session_id: str) -> LearningSession | None:
        """Load a session by ID."""
        path = self.base_dir / f"{session_id}.yaml"
        if not path.is_file():
            return None
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["status"] = LearningSessionStatus(data["status"])
        return LearningSession(**data)

    def update(self, session: LearningSession) -> None:
        """Persist an updated session."""
        self._persist(session)

    def list_all(self) -> list[LearningSession]:
        """List all sessions."""
        sessions = []
        for path in sorted(self.base_dir.glob("session-*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["status"] = LearningSessionStatus(data["status"])
            sessions.append(LearningSession(**data))
        return sessions

    def list_by_status(self, status: LearningSessionStatus) -> list[LearningSession]:
        """List sessions filtered by status."""
        return [s for s in self.list_all() if s.status == status]

    def _persist(self, session: LearningSession) -> None:
        path = self.base_dir / f"{session.id}.yaml"
        path.write_text(session.to_yaml(), encoding="utf-8")


__all__ = [
    "LearningSession",
    "LearningSessionStatus",
    "LearningSessionStore",
]
