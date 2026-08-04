"""Correction recorder — records human corrections as expert trajectories (WP-07 Task B-001).

Records what the expert (human reviewer) did differently to fix the
agent's failure. The correction actions become the expert trajectory.
"""

from __future__ import annotations

from typing import Any

from .session import LearningSession, LearningSessionStatus


class CorrectionRecorder:
    """Records the human correction as an expert trajectory."""

    def record_correction(
        self,
        session: LearningSession,
        expert_trajectory_id: str,
        correction_actions: list[dict[str, Any]],
    ) -> LearningSession:
        """Record the expert's correction.

        Args:
            session: The learning session to update.
            expert_trajectory_id: The trajectory ID of the corrected execution.
            correction_actions: List of typed actions the expert took
                (e.g., [{"tool": "flow.patch", "op": "updateNodeConfig", ...}]).

        Returns:
            Updated session with status=CORRECTED.
        """
        session.expert_trajectory_id = expert_trajectory_id
        session.correction_actions = correction_actions
        session.status = LearningSessionStatus.CORRECTED
        return session


__all__ = ["CorrectionRecorder"]
