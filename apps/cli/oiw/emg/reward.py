"""Reward vector extension (WP-05 Task 15).

Spec ref: §15.8 (Reward Vector).

Extends the WP-04 reward vector from 4 dimensions to 9, adding:
  - deployment_success (from Task 7 VERIFIED state)
  - runtime_stability (from post-deploy logs)
  - hard_gates (4 boolean gates that prevent promotion)

The reward vector is what the EMG uses to rank insights — trajectories
with higher reward are preferred for matching and retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RewardVector:
    """Full reward vector per spec §15.8.

    9 dimensions, all normalized to [0, 1] except hard_gates (booleans).
    """

    # Existing dimensions (WP-04)
    structural_validity: float = 0.0
    unit_tests: float = 0.0
    security_policy: float = 0.0
    completion: float = 0.0
    corrections_needed: float = 0.0

    # New Phase 4 dimensions (WP-05 Task 15)
    deployment_success: float = 0.0
    runtime_stability: float = 0.0

    # Hard gates (spec §15.8) — any False prevents promotion
    hard_gates: dict[str, bool] = field(
        default_factory=lambda: {
            "no_secret_leakage": True,
            "no_unauthorized_deployment": True,
            "no_critical_security": True,
            "no_corrupt_artifact": True,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "structuralValidity": self.structural_validity,
            "unitTests": self.unit_tests,
            "securityPolicy": self.security_policy,
            "completion": self.completion,
            "correctionsNeeded": self.corrections_needed,
            "deploymentSuccess": self.deployment_success,
            "runtimeStability": self.runtime_stability,
            "hardGates": dict(self.hard_gates),
        }

    @property
    def all_hard_gates_passed(self) -> bool:
        """True if all hard gates are True."""
        return all(self.hard_gates.values())

    @property
    def overall_score(self) -> float:
        """Weighted average of the 7 scalar dimensions (excluding hard gates).

        Hard gates are checked separately via `all_hard_gates_passed`.
        """
        weights = {
            "structural_validity": 0.2,
            "unit_tests": 0.15,
            "security_policy": 0.15,
            "completion": 0.15,
            "corrections_needed": 0.1,
            "deployment_success": 0.15,
            "runtime_stability": 0.1,
        }
        total = (
            self.structural_validity * weights["structural_validity"]
            + self.unit_tests * weights["unit_tests"]
            + self.security_policy * weights["security_policy"]
            + self.completion * weights["completion"]
            + self.corrections_needed * weights["corrections_needed"]
            + self.deployment_success * weights["deployment_success"]
            + self.runtime_stability * weights["runtime_stability"]
        )
        return total


def compute_reward(
    completion: bool,
    test_pass_rate: float,
    has_security_errors: bool,
    corrections: int,
    total_steps: int,
    deployment_state: str | None = None,
    runtime_stability: float | None = None,
    has_secret_leakage: bool = False,
    has_unauthorized_deployment: bool = False,
    has_critical_security: bool = False,
    has_corrupt_artifact: bool = False,
) -> RewardVector:
    """Compute the full 9-dimension reward vector.

    Args:
        completion: True if the agent execution completed successfully.
        test_pass_rate: fraction of tests that passed (0.0–1.0).
        has_security_errors: True if validation found security errors.
        corrections: number of LLM corrections requested during execution.
        total_steps: total steps in the plan.
        deployment_state: None | 'DEPLOYED' | 'VERIFIED' (from state machine).
        runtime_stability: 0.0–1.0 from post-deploy log analysis.
        has_secret_leakage: True if any secret was leaked.
        has_unauthorized_deployment: True if deployment bypassed approval.
        has_critical_security: True if critical security issue found.
        has_corrupt_artifact: True if artifact is corrupt.

    Returns:
        RewardVector with all 9 dimensions populated.
    """
    # deployment_success: 1.0 if VERIFIED, 0.5 if DEPLOYED, 0.0 otherwise
    if deployment_state == "VERIFIED":
        deploy_score = 1.0
    elif deployment_state == "DEPLOYED":
        deploy_score = 0.5
    else:
        deploy_score = 0.0

    return RewardVector(
        structural_validity=1.0 if not has_security_errors else 0.0,
        unit_tests=test_pass_rate,
        security_policy=0.0 if has_security_errors else 1.0,
        completion=1.0 if completion else 0.0,
        corrections_needed=1.0 - (corrections / max(total_steps, 1)),
        deployment_success=deploy_score,
        runtime_stability=runtime_stability or 0.0,
        hard_gates={
            "no_secret_leakage": not has_secret_leakage,
            "no_unauthorized_deployment": not has_unauthorized_deployment,
            "no_critical_security": not has_critical_security,
            "no_corrupt_artifact": not has_corrupt_artifact,
        },
    )


__all__ = ["RewardVector", "compute_reward"]
