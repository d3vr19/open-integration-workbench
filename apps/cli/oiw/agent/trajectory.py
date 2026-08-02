"""Engineering trajectory recorder (spec §15.2, §15.4, §15.5, §15.17).

Every agent session produces one EngineeringTrajectory YAML file under
`.oiw/trajectories/{traj_id}.yaml`. The trajectory is the data substrate
that EMG Phase B (§15.9) consumes to build action decision graphs.

A trajectory has three parts:
  1. metadata   — ids, base revision, timestamps
  2. spec.query — the raw + normalized user requirement (redacted)
  3. spec.steps — list of (observation, action, result) triples
  4. spec.outcome — final status + reward vector

Design notes:
- The recorder is **synchronous**: the agent pipeline already pays an
  async round-trip to the LLM; we do not want a second async hop just
  to write YAML.
- All persisted content is redacted through `Redactor` (secrets, PII,
  SAP URLs). The raw arguments are *not* persisted — only their SHA-256
  digest. The raw tool call can be retained separately for audit if
  the operator opts in via `raw_ref` (defaults to None).
- Persistence is lazy: `record_*` calls mutate the in-memory
  trajectory; only `finalize()` writes to disk. If the process crashes
  mid-execution, no half-written YAML exists.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .redaction import Redactor

# ---------------------------------------------------------------------------
# Data model (spec §15.2)
# ---------------------------------------------------------------------------


@dataclass
class TrajectoryMetadata:
    id: str
    projectId: str
    taskId: str
    baseRevision: str
    startedAt: float  # unix epoch
    finishedAt: float | None = None
    schemaVersion: str = "1.0"


@dataclass
class TrajectoryQuery:
    raw: str = ""
    normalized: dict[str, Any] = field(default_factory=dict)


@dataclass
class ObservationRecord:
    type: str  # "project.snapshot" | "validation.result" | "test.result" | ...
    fingerprint: str  # sha256 of normalized state
    summary: dict[str, Any] = field(default_factory=dict)
    diagnosticCode: str | None = None
    diagnosticCategory: str | None = None
    componentRole: str | None = None
    targetProfile: str | None = None


@dataclass
class ActionRecord:
    type: str  # "flow.patch" | "resource.write" | "test.create" | ...
    normalized: tuple[str, ...] = ()  # (tool, op, componentType, semanticTarget, paramClass)
    argumentsDigest: str = ""  # sha256 of arguments
    rawRef: str | None = None  # audit ref; None by default


@dataclass
class ResultRecord:
    status: str  # "applied" | "failed" | "skipped" | "conflict"
    revision: str | None = None
    summary: str = ""
    diagnostics: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TrajectoryStep:
    index: int
    observation: ObservationRecord | None = None
    action: ActionRecord | None = None
    result: ResultRecord | None = None


@dataclass
class TrajectoryOutcome:
    status: str = "in_progress"  # in_progress | success | failed | rejected | conflict
    reward: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrajectorySpec:
    query: TrajectoryQuery = field(default_factory=TrajectoryQuery)
    steps: list[TrajectoryStep] = field(default_factory=list)
    outcome: TrajectoryOutcome = field(default_factory=TrajectoryOutcome)


@dataclass
class EngineeringTrajectory:
    metadata: TrajectoryMetadata
    spec: TrajectorySpec = field(default_factory=TrajectorySpec)


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------


def _sha256_of_state(state: Any) -> str:
    """Stable SHA-256 of an arbitrary JSON-serializable value."""
    canonical = json.dumps(state, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TrajectoryRecorder:
    """Build and persist an EngineeringTrajectory.

    Usage:
        rec = TrajectoryRecorder(project_id="order-to-s4",
                                  task_id="task-abc123",
                                  base_revision="2a4befc")
        rec.set_query(raw_text, normalized_requirement)
        for step in plan.steps:
            rec.record_observation(step_index=i, obs_type="pre-action", state=...)
            result = dispatch_tool(step.tool, step.arguments)
            rec.record_action(
                step_index=i,
                action_type=step.tool,
                normalized=normalize_action(step.tool, step.arguments),
                arguments_digest=arguments_digest(step.arguments),
                result_status="applied" if result.ok else "failed",
                result_summary=result.summary,
            )
        rec.finalize(status="success", reward={"test_pass_rate": 1.0})
    """

    def __init__(
        self,
        project_id: str,
        task_id: str,
        base_revision: str,
        redactor: Redactor | None = None,
        started_at: float | None = None,
        persist_dir: str | os.PathLike[str] | None = None,
    ):
        self.trajectory = EngineeringTrajectory(
            metadata=TrajectoryMetadata(
                id=f"traj-{uuid.uuid4().hex[:12]}",
                projectId=project_id,
                taskId=task_id,
                baseRevision=base_revision,
                startedAt=started_at if started_at is not None else time.time(),
            ),
        )
        self._redactor = redactor or Redactor()
        self._persist_dir = Path(persist_dir) if persist_dir else None
        self._last_observation: dict[int, ObservationRecord] = {}

    # ----- query -----

    def set_query(self, raw: str, normalized: Any) -> None:
        """Record the (redacted) user requirement.

        `normalized` may be a dataclass (we call asdict on it) or a dict.
        """
        self.trajectory.spec.query.raw = self._redactor.redact(raw)
        if hasattr(normalized, "__dataclass_fields__"):
            try:
                normalized = asdict(normalized)
            except TypeError:
                normalized = {"_repr": repr(normalized)}
        elif not isinstance(normalized, dict):
            normalized = {"_value": str(normalized)}
        self.trajectory.spec.query.normalized = self._redactor.redact_dict(normalized)

    # ----- per-step recording -----

    def record_observation(
        self,
        step_index: int,
        obs_type: str,
        state: Any,
        diagnostic_code: str | None = None,
        diagnostic_category: str | None = None,
        component_role: str | None = None,
        target_profile: str | None = None,
    ) -> ObservationRecord:
        """Capture the pre-action observation for a step.

        `state` is JSON-serialized for fingerprinting and redacted for
        persistence. Large states should be summarized by the caller
        before passing in.
        """
        fingerprint = _sha256_of_state(state)
        summary = (
            self._redactor.redact_dict(state)
            if isinstance(state, dict)
            else {"_value": self._redactor.redact(str(state))}
        )
        obs = ObservationRecord(
            type=obs_type,
            fingerprint=fingerprint,
            summary=summary,
            diagnosticCode=diagnostic_code,
            diagnosticCategory=diagnostic_category,
            componentRole=component_role,
            targetProfile=target_profile,
        )
        self._last_observation[step_index] = obs
        return obs

    def record_action(
        self,
        step_index: int,
        action_type: str,
        normalized: tuple[str, ...],
        arguments_digest: str,
        result_status: str,
        result_summary: str,
        revision: str | None = None,
        diagnostics: list[dict[str, Any]] | None = None,
        raw_ref: str | None = None,
    ) -> TrajectoryStep:
        """Record an action and its result. Closes out the step.

        The action's observation is whatever was last recorded for this
        step_index via `record_observation` (or None if none was recorded).
        """
        action = ActionRecord(
            type=action_type,
            normalized=tuple(str(x) for x in normalized),
            argumentsDigest=arguments_digest,
            rawRef=raw_ref,
        )
        result = ResultRecord(
            status=result_status,
            revision=revision,
            summary=self._redactor.redact(result_summary),
            diagnostics=[
                self._redactor.redact_dict(d) if isinstance(d, dict) else d for d in (diagnostics or [])
            ],
        )
        step = TrajectoryStep(
            index=step_index,
            observation=self._last_observation.get(step_index),
            action=action,
            result=result,
        )
        self.trajectory.spec.steps.append(step)
        return step

    # ----- finalize -----

    def finalize(self, status: str, reward: dict[str, Any]) -> Path:
        """Mark the trajectory done and persist it to disk.

        Returns the path to the persisted YAML. Idempotent: re-calling
        finalize() overwrites the same file with the latest outcome.
        """
        self.trajectory.metadata.finishedAt = time.time()
        self.trajectory.spec.outcome.status = status
        self.trajectory.spec.outcome.reward = self._redactor.redact_dict(reward)
        return self._persist()

    def _persist(self) -> Path:
        """Write the trajectory to .oiw/trajectories/{id}.yaml.

        Honors `persist_dir` if set on the recorder (used by tests);
        otherwise defaults to `<cwd>/.oiw/trajectories/`.
        """
        out_dir = self._persist_dir if self._persist_dir is not None else Path.cwd() / ".oiw" / "trajectories"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{self.trajectory.metadata.id}.yaml"
        data = self.to_dict()
        path.write_text(
            yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path

    def to_dict(self) -> dict[str, Any]:
        """Serialize the trajectory to a JSON/YAML-safe dict.

        Tuples (normalized action) become lists for YAML compatibility.
        """
        d = asdict(self.trajectory)
        for step in d["spec"]["steps"]:
            if step.get("action") and isinstance(step["action"].get("normalized"), tuple):
                step["action"]["normalized"] = list(step["action"]["normalized"])
        return d

    @property
    def trajectory_id(self) -> str:
        return self.trajectory.metadata.id


__all__ = [
    "TrajectoryRecorder",
    "EngineeringTrajectory",
    "TrajectoryMetadata",
    "TrajectoryQuery",
    "TrajectorySpec",
    "TrajectoryOutcome",
    "TrajectoryStep",
    "ObservationRecord",
    "ActionRecord",
    "ResultRecord",
]
