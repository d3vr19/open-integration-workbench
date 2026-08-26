"""P5c reward function v1 — tenant-oracle verdicts feed the reward vector.

Functional iFlow = reward (p5-p6-plan.md §2/§5c): a calibration report's
deploy/message/MPL evidence maps onto the 9-dim RewardVector, and failed
runs auto-capture as learning sessions so the EMG grows from every oracle
run, not just agent sessions.
"""

from __future__ import annotations

from pathlib import Path

from ..emg.reward import RewardVector, compute_reward
from ..learn.recorder import AttemptRecorder
from ..learn.session import LearningSessionStore
from .calibrate import CalibrationReport


def reward_from_calibration(report: CalibrationReport) -> RewardVector:
    """Map one oracle run onto the 9-dim reward vector.

    Semantics:
      - completion       : STARTED + message exercised + every MPL COMPLETED
      - unit_tests       : MPL pass rate (proxy: execution telemetry)
      - runtime_stability: same pass rate over pulled rows
      - deployment_success: STARTED→VERIFIED(1.0); deploy-accepted only→0.5
      - structural/security dims: not observable here → neutral-pass
        (validation owns them; hard gates stay True so oracle rewards are
        never blocked by absent security telemetry).
    """
    started = report.final_status == "STARTED"
    rows = report.mpl_rows
    if rows:
        completed = sum(1 for r in rows if r.get("Status") == "COMPLETED")
        stability = completed / len(rows)
    else:
        # No MPL evidence: bare-started flows count stable; anything else 0.
        stability = 1.0 if started and report.error_detail is None else 0.0

    completion = bool(started and report.message_sent and stability >= 1.0)
    if started and report.deploy_accepted:
        deployment_state = "VERIFIED"
    elif report.deploy_accepted:
        deployment_state = "DEPLOYED"
    else:
        deployment_state = None

    return compute_reward(
        completion=completion,
        test_pass_rate=stability,
        has_security_errors=False,
        corrections=0,
        total_steps=1,
        deployment_state=deployment_state,
        runtime_stability=stability,
    )


def failure_diagnostic(report: CalibrationReport) -> str:
    """Short machine-ish diagnostic code for a failed oracle run."""
    if not report.uploaded_ok:
        return "ORACLE-UPLOAD-REJECTED"
    if not report.deploy_accepted:
        return "ORACLE-DEPLOY-REJECTED"
    if report.final_status == "ERROR":
        return "ORACLE-RUNTIME-START-FAILED"
    if report.final_status == "TIMEOUT":
        return "ORACLE-DEPLOY-POLL-TIMEOUT"
    if report.message_sent and any(r.get("Status") != "COMPLETED" for r in report.mpl_rows or []):
        return "ORACLE-MESSAGE-FAILED"
    return "ORACLE-INCOMPLETE"


async def record_oracle_outcome(
    report: CalibrationReport,
    project_path: Path | None = None,
    *,
    capture_failures: bool = False,
) -> RewardVector:
    """Compute the reward; optionally capture failures as learning sessions."""
    reward = reward_from_calibration(report)
    if capture_failures and reward.overall_score() < 1.0 and project_path is not None:
        store = LearningSessionStore()
        session = store.create(
            requirement=f"oracle calibration of {report.package_id}/{report.artifact_id}",
            project_id=str(project_path),
            flow_id=report.artifact_id,
        )
        AttemptRecorder.record_failure(
            session,
            diagnostic=failure_diagnostic(report),
            details=report.error_detail or f"final_status={report.final_status}",
        )
        store.update(session)
    return reward


def reward_section(reward: RewardVector) -> dict:
    """YAML-ready block appended to calibration reports."""
    return {
        "reward": {
            "overall": round(reward.overall_score, 4),
            "dimensions": {
                "structural_validity": reward.structural_validity,
                "unit_tests": reward.unit_tests,
                "security_policy": reward.security_policy,
                "completion": reward.completion,
                "corrections_needed": reward.corrections_needed,
                "deployment_success": reward.deployment_success,
                "runtime_stability": reward.runtime_stability,
            },
            "all_hard_gates_passed": reward.all_hard_gates_passed,
        }
    }
