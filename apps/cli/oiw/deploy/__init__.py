"""Deployment pipeline package (WP-05 Tasks 3-4, 7).

Spec ref: §18 (Tenant Connectivity), §18.5 (Deployment State Machine),
§18.6 (Drift Detection).
"""

from __future__ import annotations

from .drift import DriftDetector, DriftReport
from .state_machine import (
    DeploymentEvent,
    DeploymentState,
    DeploymentStateMachine,
    InvalidTransitionError,
    TransitionRecord,
)

__all__ = [
    "DeploymentState",
    "DeploymentEvent",
    "DeploymentStateMachine",
    "InvalidTransitionError",
    "TransitionRecord",
    "DriftDetector",
    "DriftReport",
]
