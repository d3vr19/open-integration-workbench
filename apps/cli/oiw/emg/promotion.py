"""Memory promotion workflow (WP-05 Task 14).

Spec ref: §15.10 (Memory Promotion).

State machine for promoting a captured trajectory through verification,
matching, insight generation, review, and approval to project-level
availability.

States: CAPTURED → REDACTED → OUTCOME_VERIFIED → MATCHED →
         INSIGHT_GENERATED → REVIEWED → PROJECT_APPROVED
         (+ DEPRECATED, REVOKED as terminal states)

Each transition is validated. The workflow ensures insights are only
retrievable after passing quality gates (redaction, verification, review).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class MemoryPromotionState(StrEnum):
    """Memory promotion lifecycle states (spec §15.10)."""

    CAPTURED = "CAPTURED"
    REDACTED = "REDACTED"
    OUTCOME_VERIFIED = "OUTCOME_VERIFIED"
    MATCHED = "MATCHED"
    INSIGHT_GENERATED = "INSIGHT_GENERATED"
    REVIEWED = "REVIEWED"
    PROJECT_APPROVED = "PROJECT_APPROVED"
    DEPRECATED = "DEPRECATED"
    REVOKED = "REVOKED"


# Allowed transitions (spec §15.10).
PROMOTION_TRANSITIONS: dict[MemoryPromotionState, list[MemoryPromotionState]] = {
    MemoryPromotionState.CAPTURED: [
        MemoryPromotionState.REDACTED,
        MemoryPromotionState.DEPRECATED,
        MemoryPromotionState.REVOKED,
    ],
    MemoryPromotionState.REDACTED: [
        MemoryPromotionState.OUTCOME_VERIFIED,
        MemoryPromotionState.DEPRECATED,
        MemoryPromotionState.REVOKED,
    ],
    MemoryPromotionState.OUTCOME_VERIFIED: [
        MemoryPromotionState.MATCHED,
        MemoryPromotionState.DEPRECATED,
        MemoryPromotionState.REVOKED,
    ],
    MemoryPromotionState.MATCHED: [
        MemoryPromotionState.INSIGHT_GENERATED,
        MemoryPromotionState.DEPRECATED,
        MemoryPromotionState.REVOKED,
    ],
    MemoryPromotionState.INSIGHT_GENERATED: [
        MemoryPromotionState.REVIEWED,
        MemoryPromotionState.DEPRECATED,
        MemoryPromotionState.REVOKED,
    ],
    MemoryPromotionState.REVIEWED: [
        MemoryPromotionState.PROJECT_APPROVED,
        MemoryPromotionState.DEPRECATED,
        MemoryPromotionState.REVOKED,
    ],
    MemoryPromotionState.PROJECT_APPROVED: [
        MemoryPromotionState.DEPRECATED,
        MemoryPromotionState.REVOKED,
    ],
    MemoryPromotionState.DEPRECATED: [],
    MemoryPromotionState.REVOKED: [],
}


class PromotionError(Exception):
    """Raised when a promotion transition is invalid or verification fails."""


@dataclass
class InsightRecord:
    """A stored insight record with its promotion state."""

    id: str
    state: MemoryPromotionState = MemoryPromotionState.CAPTURED
    trajectory_id: str | None = None
    project_id: str | None = None
    insight: Any = None  # IntraTaskInsight
    reviewed_by: str | None = None
    approved_by: str | None = None
    deprecation_reason: str | None = None
    revocation_reason: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state.value,
            "trajectoryId": self.trajectory_id,
            "projectId": self.project_id,
            "reviewedBy": self.reviewed_by,
            "approvedBy": self.approved_by,
            "deprecationReason": self.deprecation_reason,
            "revocationReason": self.revocation_reason,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class InMemoryInsightStore:
    """Simple in-memory store for insight records.

    For production, replace with a database (Postgres, SQLite, etc.).
    """

    def __init__(self) -> None:
        self._records: dict[str, InsightRecord] = {}

    def insert(self, record: InsightRecord) -> InsightRecord:
        self._records[record.id] = record
        return record

    def get(self, insight_id: str) -> InsightRecord:
        if insight_id not in self._records:
            raise KeyError(f"insight not found: {insight_id}")
        return self._records[insight_id]

    def update(self, record: InsightRecord) -> InsightRecord:
        record.updated_at = datetime.now(tz=UTC).isoformat()
        self._records[record.id] = record
        return record

    def list(
        self,
        project_id: str | None = None,
        state: MemoryPromotionState | None = None,
    ) -> list[InsightRecord]:
        results = list(self._records.values())
        if project_id is not None:
            results = [r for r in results if r.project_id == project_id]
        if state is not None:
            results = [r for r in results if r.state == state]
        return results

    def delete(self, insight_id: str) -> None:
        self._records.pop(insight_id, None)


class MemoryPromotionWorkflow:
    """Manages the promotion of insights through quality gates.

    Spec ref: §15.10.
    """

    def __init__(self, store: InMemoryInsightStore | None = None):
        self.store = store or InMemoryInsightStore()

    def record(
        self,
        trajectory_id: str,
        project_id: str,
        insight: Any = None,
    ) -> InsightRecord:
        """CAPTURED: record a new trajectory for promotion."""
        import uuid

        record = InsightRecord(
            id=f"insight-{uuid.uuid4().hex[:12]}",
            state=MemoryPromotionState.CAPTURED,
            trajectory_id=trajectory_id,
            project_id=project_id,
            insight=insight,
        )
        return self.store.insert(record)

    def redact(self, insight_id: str) -> InsightRecord:
        """REDACTED: secrets stripped (done by TrajectoryRecorder at capture)."""
        record = self.store.get(insight_id)
        self._transition(record, MemoryPromotionState.REDACTED)
        return self.store.update(record)

    def verify_outcome(
        self,
        insight_id: str,
        tests_pass: bool,
        deploy_success: bool,
    ) -> InsightRecord:
        """OUTCOME_VERIFIED: tests + deployment verified."""
        if not tests_pass or not deploy_success:
            raise PromotionError(
                f"outcome verification failed: tests_pass={tests_pass}, deploy_success={deploy_success}"
            )
        record = self.store.get(insight_id)
        self._transition(record, MemoryPromotionState.OUTCOME_VERIFIED)
        return self.store.update(record)

    def match(self, insight_id: str) -> InsightRecord:
        """MATCHED: graph matching completed."""
        record = self.store.get(insight_id)
        self._transition(record, MemoryPromotionState.MATCHED)
        return self.store.update(record)

    def generate_insight(self, insight_id: str, insight: Any = None) -> InsightRecord:
        """INSIGHT_GENERATED: machine-readable correction extracted."""
        record = self.store.get(insight_id)
        if insight is not None:
            record.insight = insight
        self._transition(record, MemoryPromotionState.INSIGHT_GENERATED)
        return self.store.update(record)

    def review(self, insight_id: str, reviewer: str) -> InsightRecord:
        """REVIEWED: human reviewed."""
        if not reviewer:
            raise PromotionError("reviewer identity is required")
        record = self.store.get(insight_id)
        record.reviewed_by = reviewer
        self._transition(record, MemoryPromotionState.REVIEWED)
        return self.store.update(record)

    def approve_project(self, insight_id: str, approver: str) -> InsightRecord:
        """PROJECT_APPROVED: available within project."""
        if not approver:
            raise PromotionError("approver identity is required")
        record = self.store.get(insight_id)
        record.approved_by = approver
        self._transition(record, MemoryPromotionState.PROJECT_APPROVED)
        return self.store.update(record)

    def deprecate(self, insight_id: str, reason: str) -> InsightRecord:
        """DEPRECATED: adapter/compiler changed."""
        record = self.store.get(insight_id)
        record.deprecation_reason = reason
        self._transition(record, MemoryPromotionState.DEPRECATED)
        return self.store.update(record)

    def revoke(self, insight_id: str, reason: str) -> InsightRecord:
        """REVOKED: caused incident; excluded from retrieval."""
        record = self.store.get(insight_id)
        record.revocation_reason = reason
        self._transition(record, MemoryPromotionState.REVOKED)
        return self.store.update(record)

    def is_retrievable(self, insight_id: str) -> bool:
        """Check if an insight is retrievable (PROJECT_APPROVED only)."""
        record = self.store.get(insight_id)
        return record.state == MemoryPromotionState.PROJECT_APPROVED

    def _transition(self, record: InsightRecord, target: MemoryPromotionState) -> None:
        """Validate + apply a state transition."""
        current = record.state
        allowed = PROMOTION_TRANSITIONS.get(current, [])
        if target not in allowed:
            raise PromotionError(
                f"invalid promotion transition: {current.value} → {target.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        record.state = target


__all__ = [
    "MemoryPromotionState",
    "PromotionError",
    "InsightRecord",
    "InMemoryInsightStore",
    "MemoryPromotionWorkflow",
    "PROMOTION_TRANSITIONS",
]
