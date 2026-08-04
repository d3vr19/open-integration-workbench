"""Attempt recorder — captures agent attempts and failures (WP-07 Task B-001).

Records the agent's execution trajectory when it attempts a task.
If the attempt fails, records the failure diagnostic + details.
"""

from __future__ import annotations

from .session import LearningSession, LearningSessionStatus


class AttemptRecorder:
    """Records the agent's attempt and any failure."""

    def record_attempt(
        self,
        session: LearningSession,
        trajectory_id: str,
    ) -> LearningSession:
        """Record the agent's trajectory ID from its attempt.

        Args:
            session: The learning session to update.
            trajectory_id: The trajectory ID from the agent's execution.

        Returns:
            Updated session.
        """
        session.failed_trajectory_id = trajectory_id
        return session

    def record_failure(
        self,
        session: LearningSession,
        diagnostic: str,
        details: str,
    ) -> LearningSession:
        """Record the failure mode.

        Args:
            session: The learning session to update.
            diagnostic: The diagnostic code (e.g., "OIW-E003").
            details: Human-readable description of what went wrong.

        Returns:
            Updated session with status=FAILED_RECORDED.
        """
        session.failure_diagnostic = diagnostic
        session.failure_details = details
        session.status = LearningSessionStatus.FAILED_RECORDED
        return session


__all__ = ["AttemptRecorder"]
