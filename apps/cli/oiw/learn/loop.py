"""Phase C — closed LLM-free learning loop (p5-p6-plan.md §5C).

Three seams that turn one-shot machinery into a self-growing, LLM-free loop:

  C-1  record_oracle_outcome hookup: every calibration report (the tenant
       oracle's verdict) promotes a real insight + task node into the
       durable EMG store when the run SUCCEEDED (STARTED + message
       exercised + all MPL rows COMPLETED). The insight's
       successful_workflow is the flow's actual node sequence — expert
       knowledge harvested from reality, not synthesis. Provenance
       records source=tenant-oracle so downstream consumers know these
       pieces are live-proven.

  C-2  failure→corpus automation: every FAILED oracle verdict and every
       parity-suite `mismatched` case files a corpus candidate YAML under
       packages/parity-corpus/candidates/. A candidate is triage-ready
       input — it NEVER auto-promotes. Triage decides: exporter fix
       (bundle bytes wrong) or executor test (local semantics wrong) or
       discard (tenant drift; blood law: oracle verdicts are
       point-in-time).

  C-3  (see learn/harvest_schedule.py) pattern-book freshness — the
       harvester refuses to re-crawl until the cached pattern book is
       older than the configured TTL, so a scheduled crawler is cheap.

Laws honored here:
  - Teacher (LLM) is never summoned by this loop — it is LLM-free by
    construction (operator decision, 2026-08-26).
  - Honest provenance: simulated-world vs tenant knowledge is labeled
    on every record.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..agent.interpreter import NormalizedRequirement
from ..emg.insight.compiler import InsightProvenance, IntraTaskInsight
from ..emg.promotion import InsightRecord, MemoryPromotionState
from ..project import IntegrationFlow, Project, ProjectError

ORACLE_PROVENANCE_SOURCE = "tenant-oracle"
_PARITY_PROVENANCE_SOURCE = "parity-suite"

HARD_GATE_REWARD = 1.0


@dataclasses.dataclass
class LoopOutcome:
    """Result of feeding one oracle verdict into the learning loop."""

    promoted: bool = False
    insight_id: str | None = None
    candidate_id: str | None = None
    candidate_path: Path | None = None
    reason: str = ""


def _flow_success_shape(flow: IntegrationFlow) -> list[dict[str, Any]]:
    """Serialize the flow's node chain into insight successful_workflow form.

    Mirrors the shape produced by CommonSubgraphExtractor serialization
    (``{"action": (tool, op, componentType, ...), "result": "applied"}``)
    so EMG scoring + injection work unchanged on oracle-harvested pieces.
    """
    order = _execution_order(flow)
    workflow: list[dict[str, Any]] = []
    for idx, node_id in enumerate(order):
        node = _find_node(flow, node_id)
        if node is None:
            continue
        workflow.append(
            {
                "action": ("flow.patch", "addNode", node.type, node.id),
                "result": "applied",
                "order": idx,
            }
        )
    return workflow


def _execution_order(flow: IntegrationFlow) -> list[str]:
    """Deterministic node order: entrypoints, then a BFS over edges."""
    seen: list[str] = []
    queue: list[str] = [e.id for e in flow.entrypoints]
    visited: set[str] = set()
    while queue:
        nid = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        seen.append(nid)
        for edge in flow.edges:
            if edge.from_ == nid and edge.to not in visited:
                queue.append(edge.to)
    # Any nodes not reachable (isolated) still belong in the shape —
    # sorted for determinism.
    for n in sorted(flow.nodes, key=lambda n: n.id):
        if n.id not in visited:
            seen.append(n.id)
    return seen


def _find_node(flow: IntegrationFlow, node_id: str) -> Any | None:
    for e in flow.entrypoints:
        if e.id == node_id:
            return e
    for n in flow.nodes:
        if n.id == node_id:
            return n
    return None


def oracle_insight_from_flow(
    flow: IntegrationFlow,
    report: Any,
) -> IntraTaskInsight:
    """Build an IntraTaskInsight from a live-proven flow + its oracle report."""
    provenance = InsightProvenance(
        exploration_trajectory_id=f"oracle:{report.artifact_id}",
        expert_trajectory_id=f"oracle:{report.artifact_id}",
        match_stage="oracle",
    )
    insight = IntraTaskInsight(
        task_id=f"oracle-{report.artifact_id}-{uuid.uuid4().hex[:6]}",
        successful_workflow=_flow_success_shape(flow),
        corrections=[],  # oracle-harvested pieces carry no corrections
        provenance=provenance,
    )
    # Extra, non-schema provenance detail for consumers + audit.
    insight.oracle_detail = {
        "source": ORACLE_PROVENANCE_SOURCE,
        "packageId": report.package_id,
        "artifactId": report.artifact_id,
        "finalStatus": report.final_status,
        "messageSent": report.message_sent,
        "mplRows": len(report.mpl_rows or []),
        "harvestedAt": datetime.now(tz=UTC).isoformat(),
    }
    return insight


def promote_oracle_outcome(
    report: Any,
    project_path: Path,
    durable_store: Any,
    *,
    requirement_text: str | None = None,
    confidentiality_scope: str = "organization",
) -> LoopOutcome:
    """C-1: promote a SUCCEEDED oracle run into the durable EMG store.

    Promotion uses the seed-corpus precedent (auto-approve with real
    provenance) because the evidence here is stronger than synthesis:
    the tenant itself accepted the bundle, started it, and completed the
    message. Failed runs are NOT promoted here — they go to the corpus
    candidates (see file_oracle_failure).
    """
    started = report.final_status == "STARTED"
    rows = report.mpl_rows or []
    all_completed = bool(rows) and all(r.get("Status") == "COMPLETED" for r in rows)
    full_success = bool(started and report.message_sent and all_completed)

    if not full_success:
        return LoopOutcome(
            promoted=False,
            reason=(
                f"oracle run not fully successful (status={report.final_status}, "
                f"messageSent={report.message_sent}, mplRows={len(rows)}); "
                "not promoting — see corpus candidates"
            ),
        )

    try:
        project = Project.load(project_path)
    except ProjectError as exc:
        return LoopOutcome(promoted=False, reason=f"project load failed: {exc}")

    flows = sorted(project.flows, key=lambda f: f.id)
    if not flows:
        return LoopOutcome(promoted=False, reason="project has no flows")
    flow = flows[0] if len(flows) == 1 else _flow_matching_artifact(flows, report.artifact_id)
    if flow is None:
        return LoopOutcome(
            promoted=False,
            reason=f"cannot identify flow for artifact {report.artifact_id!r} "
            f"({len(flows)} flows in project)",
        )

    requirement = requirement_text or (
        f"Live-proven tenant flow {report.artifact_id}: "
        f"entrypoints {sorted({e.type for e in flow.entrypoints})}, "
        f"steps {sorted({n.type for n in flow.nodes})}"
    )
    normalized = NormalizedRequirement(
        intent="create-flow",
        archetype=(flow.labels or {}).get("archetype"),
        operations=sorted({n.type.split(".")[0] for n in flow.nodes if "." in n.type}),
        components=sorted({n.type for n in flow.nodes} | {e.type for e in flow.entrypoints}),
        constraints=["must-have-error-handling", "no-secrets-inline"],
        confidence=1.0,
        raw=requirement,
    )

    insight = oracle_insight_from_flow(flow, report)

    record = InsightRecord(
        id=f"insight-{uuid.uuid4().hex[:12]}",
        state=MemoryPromotionState.PROJECT_APPROVED,
        trajectory_id=f"oracle:{report.artifact_id}",
        project_id=project.id,
        insight=insight,
        reviewed_by="tenant-oracle-bot",
        approved_by="tenant-oracle-bot",
    )
    durable_store.upsert_insight(record)
    durable_store.upsert_task_from_requirement(
        normalized,
        task_id=insight.task_id,
        project_id=project.id,
        insight_ref=record.id,
        reward={"overall": HARD_GATE_REWARD, "source": ORACLE_PROVENANCE_SOURCE},
        approval="PROJECT_APPROVED",
        # Operator's own tenant knowledge — organization scope by default
        # (same as CodeJam corpus), overridable for stricter tenancy.
        confidentiality_scope=confidentiality_scope,
    )
    durable_store.save()

    return LoopOutcome(
        promoted=True,
        insight_id=record.id,
        reason=f"promoted oracle piece {insight.task_id} (artifact {report.artifact_id})",
    )


def _flow_matching_artifact(flows: list[IntegrationFlow], artifact_id: str) -> IntegrationFlow | None:
    aid = (artifact_id or "").lower()
    for f in flows:
        if f.id.lower() == aid or (f.name or "").lower() == aid:
            return f
    return flows[0] if len(flows) == 1 else None


# ---------------------------------------------------------------------------
# C-2: failure → corpus automation
# ---------------------------------------------------------------------------


def file_oracle_failure(
    report: Any,
    candidates_dir: Path,
    *,
    project_path: Path | None = None,
    source: str = ORACLE_PROVENANCE_SOURCE,
) -> LoopOutcome:
    """File a corpus candidate for a failed oracle run.

    The candidate is a YAML record with everything triage needs:
    verdict, diagnostic, the report, and a suggested triage class.
    Nothing is auto-promoted and nothing enters the exporter — candidates
    are the input to a human/agent triage step, per the sequencing law
    (calibration before coverage before autonomy).
    """
    candidates_dir.mkdir(parents=True, exist_ok=True)
    diagnostic = _oracle_diagnostic(report)
    candidate_id = f"oracle-fail-{report.artifact_id or 'unknown'}-{uuid.uuid4().hex[:6]}"
    payload = {
        "candidate": {
            "id": candidate_id,
            "kind": "oracle-failure",
            "createdAt": datetime.now(tz=UTC).isoformat(),
            "provenance": {
                "source": source,
                "packageId": report.package_id,
                "artifactId": report.artifact_id,
                "isReal": True,
            },
            "verdict": {
                "finalStatus": report.final_status,
                "uploadedOk": report.uploaded_ok,
                "deployAccepted": report.deploy_accepted,
                "messageSent": report.message_sent,
                "httpResponseStatus": report.http_response_status,
                "mplRows": len(report.mpl_rows or []),
                "errorDetail": report.error_detail,
                "diagnostic": diagnostic,
            },
            "suggestedTriage": _suggest_triage(diagnostic),
            "notes": [
                "Blood law: oracle verdicts are point-in-time — check for the "
                "deploy-rate wedge before treating this as content failure.",
                "Triage options: exporter-fix | executor-test | tenant-drift | discard.",
            ],
        }
    }
    if project_path is not None:
        payload["candidate"]["project"] = str(project_path)
    path = candidates_dir / f"{candidate_id}.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return LoopOutcome(
        promoted=False,
        candidate_id=candidate_id,
        candidate_path=path,
        reason=f"filed corpus candidate {candidate_id} ({diagnostic})",
    )


def file_parity_miss(
    row: dict[str, Any],
    candidates_dir: Path,
) -> LoopOutcome:
    """File a corpus candidate for a parity-suite `mismatched` case.

    Every parity failure becomes either an exporter fix or an executor
    test case (p5-p6-plan.md §2 M3) — the candidate is where that
    decision is recorded after triage.
    """
    candidates_dir.mkdir(parents=True, exist_ok=True)
    name = str(row.get("name") or "case")
    candidate_id = f"parity-miss-{name}-{uuid.uuid4().hex[:6]}"
    payload = {
        "candidate": {
            "id": candidate_id,
            "kind": "parity-mismatch",
            "createdAt": datetime.now(tz=UTC).isoformat(),
            "provenance": {
                "source": _PARITY_PROVENANCE_SOURCE,
                "case": name,
                "project": row.get("project"),
            },
            "verdict": {
                "localStatus": row.get("localStatus"),
                "oracle": row.get("oracle"),
                "details": row.get("details"),
                "oracleReportAgeHours": row.get("oracleReportAgeHours"),
            },
            "suggestedTriage": _suggest_triature_parity(row),
            "notes": [
                "A mismatch may be tenant drift (stale oracle) rather than "
                "local infidelity — check oracleReportAgeHours first.",
            ],
        }
    }
    path = candidates_dir / f"{candidate_id}.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return LoopOutcome(
        promoted=False,
        candidate_id=candidate_id,
        candidate_path=path,
        reason=f"filed parity-miss candidate {candidate_id}",
    )


def _oracle_diagnostic(report: Any) -> str:
    from ..tenant.oracle_feedback import failure_diagnostic

    return failure_diagnostic(report)


def _suggest_triage(diagnostic: str) -> str:
    if diagnostic == "ORACLE-RUNTIME-START-FAILED":
        return "exporter-fix"
    if diagnostic == "ORACLE-MESSAGE-FAILED":
        return "executor-test"
    if diagnostic in ("ORACLE-UPLOAD-REJECTED", "ORACLE-DEPLOY-REJECTED"):
        return "exporter-fix"
    return "triage-required"


def _suggest_triature_parity(row: dict[str, Any]) -> str:
    oracle = (row.get("oracle") or {}) if isinstance(row.get("oracle"), dict) else {}
    status = str(oracle.get("finalStatus") or "")
    local = str(row.get("localStatus") or "")
    if status == "ERROR" and local == "PASS":
        # Local says fine, tenant says no — bundle bytes suspect.
        return "exporter-fix"
    if status == "STARTED" and local == "FAIL":
        # Tenant ran fine, local disagrees — local semantics suspect.
        return "executor-test"
    return "triage-required"


def record_oracle_run(
    report: Any,
    project_path: Path,
    durable_store: Any,
    candidates_dir: Path,
    *,
    requirement_text: str | None = None,
) -> LoopOutcome:
    """Route one oracle verdict through the loop: promote or file.

    This is the single call `oiw tenant calibrate` makes after writing
    its report. Success → EMG promotion (C-1). Failure → corpus
    candidate (C-2). Either way the loop closes without any LLM.
    """
    started = report.final_status == "STARTED"
    rows = report.mpl_rows or []
    all_completed = bool(rows) and all(r.get("Status") == "COMPLETED" for r in rows)
    full_success = bool(started and report.message_sent and all_completed)

    if full_success:
        return promote_oracle_outcome(report, project_path, durable_store, requirement_text=requirement_text)
    if (
        report.final_status in ("ERROR", "TIMEOUT")
        or not report.uploaded_ok
        or (report.message_sent and any(r.get("Status") != "COMPLETED" for r in rows))
    ):
        return file_oracle_failure(report, candidates_dir, project_path=project_path)
    return LoopOutcome(
        promoted=False,
        reason=(
            f"oracle run incomplete (status={report.final_status}, "
            f"messageSent={report.message_sent}); nothing promoted or filed"
        ),
    )


__all__ = [
    "LoopOutcome",
    "ORACLE_PROVENANCE_SOURCE",
    "file_oracle_failure",
    "file_parity_miss",
    "oracle_insight_from_flow",
    "promote_oracle_outcome",
    "record_oracle_run",
]
