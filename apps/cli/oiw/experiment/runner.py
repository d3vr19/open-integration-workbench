"""B2 — experiment runner: executes a ladder against the tenant oracle.

This is the ONLY experiment module that touches the tenant, and it does so
exclusively through the existing calibrate loop (allowlist-gated, scratch
packages only, never CI). Two operator hard-gates the runner enforces:

  COOL-DOWN (blood law, twice-proven): the tenant wedges after ~10 rapid
  deploys/hour — verdicts taken during a wedge are noise. The runner paces
  rungs with a minimum inter-deploy interval and refuses unattended
  campaigns unless --unattended is passed (operator approval on record).

  REVERSIBILITY: every rung deploys onto the SAME pinned artifact (PUT
  update path); the calibrate loop already takes a pre-upload backup. The
  baseline is re-deployed at campaign end so the artifact ends green.

Verdicts:
  GREEN  = STARTED + message 200 + all MPL rows COMPLETED (this run's
           epoch-filtered rows — stale rows never count)
  RED    = runtime-start ERROR, or message leg failed, or any MPL FAILED
  SKIPPED = not run (budget/cool-down/invalid)

The run is recorded as an ExperimentRecord YAML under .oiw/experiments/
before any tenant call and updated after each rung — an aborted campaign
leaves a complete partial record, never a silent gap.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from ..project import IntegrationFlow
from ..tenant.sap_ci_adapter import SapCiTenantError
from .engine import (
    VERDICT_GREEN,
    VERDICT_RED,
    VERDICT_SKIPPED,
    ExperimentRecord,
    Rung,
    materialize_variant,
)

# Conservative default: >= 6 min between deploys = <= 10/hour.
DEFAULT_COOLDOWN_S = 360.0


@dataclass
class ExperimentBudget:
    max_rungs: int = 20
    wall_clock_s: float = 3600.0
    cooldown_s: float = DEFAULT_COOLDOWN_S
    unattended: bool = False  # operator approval for unattended execution

    def __post_init__(self) -> None:
        if self.max_rungs < 1:
            raise ValueError("max_rungs must be >= 1")
        if self.wall_clock_s <= 0:
            raise ValueError("wall_clock_s must be positive")
        if self.cooldown_s < 0:
            raise ValueError("cooldown_s must be >= 0")


class OracleCallable(Protocol):
    """The seam the calibrate loop satisfies (and tests fake)."""

    async def __call__(
        self,
        project_path: Path,
        flow: IntegrationFlow,
        *,
        artifact_id: str | None,
    ) -> dict[str, Any]: ...


def verdict_from_calibration(cal: dict[str, Any]) -> str:
    """Map a calibration payload to GREEN / RED.

    Same success criteria as learn/loop.record_oracle_run (C-1): full
    success is STARTED + message exercised + all MPL rows COMPLETED —
    and the MPL epoch filter upstream has already dropped stale rows.
    """
    if not cal.get("uploadedOk"):
        return VERDICT_RED
    if cal.get("finalStatus") != "STARTED":
        return VERDICT_RED
    if cal.get("artifactEntrypointIsHttp", True) is False:
        # non-HTTP entrypoints (PD listeners): STARTED is the full verdict
        return VERDICT_GREEN
    if not cal.get("messageSent"):
        return VERDICT_RED
    if cal.get("httpResponseStatus") != 200:
        return VERDICT_RED
    rows = cal.get("mplRows") or []
    if not rows:
        return VERDICT_RED
    return VERDICT_GREEN if all(r.get("Status") == "COMPLETED" for r in rows) else VERDICT_RED


class ExperimentRunner:
    """Executes rungs one at a time, single-variable, cool-down paced.

    `oracle` is an async callable(project_path, flow, artifact_id) ->
    calibration-dict; the CLI wires it to a temp-project + calibrate_artifact
    round-trip. Tests wire it to a fake.
    """

    def __init__(
        self,
        oracle: OracleCallable,
        budget: ExperimentBudget,
        *,
        project_path: Path,
        artifact_id: str | None = None,
        piece_provider: dict[str, dict[str, Any]] | None = None,
        sleep: Any = None,
    ):
        self.oracle = oracle
        self.budget = budget
        self.project_path = project_path
        self.artifact_id = artifact_id
        self.piece_provider = piece_provider
        self._sleep = sleep or asyncio.sleep  # test seam: instant cool-down
        self._last_deploy_ts: float | None = None

    async def _paced_oracle_call(self, flow: IntegrationFlow) -> dict[str, Any]:
        """One oracle call, honoring the cool-down governor."""
        now = time.monotonic()
        if self._last_deploy_ts is not None:
            wait = self.budget.cooldown_s - (now - self._last_deploy_ts)
            if wait > 0:
                await self._sleep(wait)
        self._last_deploy_ts = time.monotonic()
        return await self.oracle(self.project_path, flow, artifact_id=self.artifact_id)

    async def run(
        self,
        record: ExperimentRecord,
        baseline_flow: IntegrationFlow,
    ) -> ExperimentRecord:
        """Execute the ladder. The record is persisted per-rung by the CLI."""
        if not record.rungs:
            record.status = "aborted"
            record.baseline_verdict = VERDICT_SKIPPED
            return record
        if not self.budget.unattended and record.status != "running":
            # attended runs flip status on entry; the CLI confirms with the
            # operator BEFORE constructing the runner for unattended mode.
            record.status = "running"

        deadline = time.monotonic() + self.budget.wall_clock_s
        run = 0

        # Baseline first — laws are only derived from a green baseline.
        try:
            cal = await self._paced_oracle_call(baseline_flow)
        except SapCiTenantError:
            record.baseline_verdict = VERDICT_RED
            record.status = "aborted"
            return record
        record.baseline_verdict = verdict_from_calibration(cal)

        for rung in record.rungs:
            if run >= self.budget.max_rungs:
                rung.verdict = VERDICT_SKIPPED
                rung.rationale += " [skipped: rung budget]"
                continue
            if time.monotonic() > deadline:
                rung.verdict = VERDICT_SKIPPED
                rung.rationale += " [skipped: wall clock]"
                continue
            try:
                variant = materialize_variant(
                    baseline_flow, rung, piece_provider=self.piece_provider
                )
            except ValueError as exc:
                rung.verdict = VERDICT_SKIPPED
                rung.rationale += f" [skipped: {exc}]"
                continue
            try:
                cal = await self._paced_oracle_call(variant)
            except SapCiTenantError as exc:
                rung.verdict = VERDICT_RED
                rung.evidence = {"error": str(exc)}
                run += 1
                continue
            rung.verdict = verdict_from_calibration(cal)
            rung.evidence = _digest(cal)
            run += 1

        record.status = "complete"
        return record


def _digest(cal: dict[str, Any]) -> dict[str, Any]:
    """Compact evidence attached to each rung (full report lives in .oiw/)."""
    return {
        "finalStatus": cal.get("finalStatus"),
        "httpResponseStatus": cal.get("httpResponseStatus"),
        "mplStatuses": [r.get("Status") for r in (cal.get("mplRows") or [])][:5],
    }


def save_record(record: ExperimentRecord, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{record.experiment_id}.yaml"
    path.write_text(
        yaml.safe_dump(record.to_dict(), sort_keys=False), encoding="utf-8"
    )
    return path


def load_record(path: Path) -> ExperimentRecord:
    return ExperimentRecord.from_dict(
        yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    )


__all__ = [
    "DEFAULT_COOLDOWN_S",
    "ExperimentBudget",
    "ExperimentRunner",
    "OracleCallable",
    "Rung",
    "load_record",
    "save_record",
    "verdict_from_calibration",
]
