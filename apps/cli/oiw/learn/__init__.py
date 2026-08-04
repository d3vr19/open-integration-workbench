"""Learning session package (WP-07 Track B).

Spec ref: §15.7, §15.8, §15.9.

Manages failed-to-expert trajectory pairs through structured learning
sessions. Each session captures an agent attempt, records the failure,
applies a human correction, and extracts the graph edit path as
correction knowledge for the EMG.
"""

from __future__ import annotations

from .corrector import CorrectionRecorder
from .pairer import TrajectoryPairer
from .recorder import AttemptRecorder
from .session import LearningSession, LearningSessionStatus
from .verifier import LearningVerifier

__all__ = [
    "LearningSession",
    "LearningSessionStatus",
    "AttemptRecorder",
    "CorrectionRecorder",
    "TrajectoryPairer",
    "LearningVerifier",
]
