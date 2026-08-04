"""Learning verifier — re-runs requirement to verify correction is retrieved (WP-07 Task B-001).

After a learning session produces a correction insight, the verifier
re-runs the same (or similar) requirement with the EMG retriever enabled.
If the agent retrieves the correction and succeeds, learning is verified.
"""

from __future__ import annotations

from typing import Any

from .session import LearningSession, LearningSessionStatus


class LearningVerifier:
    """Verifies that the EMG learned from a learning session.

    Re-runs the original requirement with the EMG retriever enabled.
    If the agent retrieves the correction insight and produces a
    successful result, the session is marked VERIFIED.
    """

    def verify(
        self,
        session: LearningSession,
        agent_result: Any,
        correction_retrieved: bool,
    ) -> LearningSession:
        """Verify that the correction was retrieved and the agent succeeded.

        Args:
            session: The learning session to verify.
            agent_result: The result from re-running the agent with EMG enabled.
            correction_retrieved: True if the EMG retriever found the correction.

        Returns:
            Updated session with status=VERIFIED (or remains EXTRACTED on failure).
        """
        success = (
            correction_retrieved
            and hasattr(agent_result, "status")
            and agent_result.status in ("COMPLETED", "SUCCESS")
        )

        if success:
            session.verification_result = "agent retrieved correction and succeeded"
            session.status = LearningSessionStatus.VERIFIED
        else:
            reason = []
            if not correction_retrieved:
                reason.append("correction not retrieved")
            if hasattr(agent_result, "status") and agent_result.status not in ("COMPLETED", "SUCCESS"):
                reason.append(f"agent status={agent_result.status}")
            session.verification_result = f"verification failed: {', '.join(reason)}"

        return session


__all__ = ["LearningVerifier"]
