"""Experiment Engine routes — expose B2 campaign records to the UI.

WP-10 Track D (contract-first, spec landed before this route module).
Read-only: campaigns are launched via `oiw experiment run` (CLI, operator-
gated); these routes serve the persisted records under
`<workspace>/.oiw/experiments/*.yaml` — the same files the CLI writes
per-rung (on_rung persistence hook, live lesson 2026-09-03).

Spec ref: packages/api-spec/openapi.yaml (tags: Experiments, Laws).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["Experiments"])


class RungModel(BaseModel):
    rungId: str
    kind: str
    target: str
    detail: dict[str, Any] = {}
    rationale: str = ""
    verdict: str = "SKIPPED"
    evidence: dict[str, Any] = {}


class ExperimentSummary(BaseModel):
    experimentId: str
    baselineFlowId: str
    hypothesis: str = ""
    createdAt: str = ""
    baselineVerdict: str = "SKIPPED"
    status: str = "draft"
    rungCount: int = 0
    greenCount: int = 0
    redCount: int = 0
    skippedCount: int = 0


class ExperimentRecord(BaseModel):
    experimentId: str
    baselineFlowId: str
    hypothesis: str = ""
    createdAt: str = ""
    baselineVerdict: str = "SKIPPED"
    status: str = "draft"
    rungs: list[RungModel] = []


def _experiments_dir() -> Path:
    """Records resolve from the workspace, like the EMG store."""
    ws = os.environ.get("OIW_WORKSPACE")
    root = Path(ws) if ws else Path.cwd()
    return Path(root) / ".oiw" / "experiments"


def _load_records() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    exp_dir = _experiments_dir()
    if not exp_dir.is_dir():
        return out
    for f in sorted(exp_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue  # corrupt record never breaks the listing
        if data.get("experimentId"):
            out.append(data)
    return out


def _to_summary(data: dict[str, Any]) -> ExperimentSummary:
    rungs = data.get("rungs") or []
    verdicts = [str(r.get("verdict") or "SKIPPED") for r in rungs]
    return ExperimentSummary(
        experimentId=str(data["experimentId"]),
        baselineFlowId=str(data.get("baselineFlowId") or ""),
        hypothesis=str(data.get("hypothesis") or ""),
        createdAt=str(data.get("createdAt") or ""),
        baselineVerdict=str(data.get("baselineVerdict") or "SKIPPED"),
        status=str(data.get("status") or "draft"),
        rungCount=len(rungs),
        greenCount=verdicts.count("GREEN"),
        redCount=verdicts.count("RED"),
        skippedCount=verdicts.count("SKIPPED"),
    )


@router.get("/experiments", response_model=list[ExperimentSummary])
def list_experiments() -> list[ExperimentSummary]:
    """List experiment campaign records (newest first by createdAt)."""
    summaries = [_to_summary(d) for d in _load_records()]
    summaries.sort(key=lambda s: s.createdAt, reverse=True)
    return summaries


@router.get("/experiments/{experiment_id}", response_model=ExperimentRecord)
def get_experiment(experiment_id: str) -> ExperimentRecord:
    """Get one campaign record with full rung detail."""
    exp_dir = _experiments_dir()
    path = exp_dir / f"{experiment_id}.yaml"
    if not path.is_file():
        # never leak existence details for path-injection style ids
        raise HTTPException(status_code=404, detail=f"experiment not found: {experiment_id}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=500, detail=f"corrupt experiment record: {exc}") from exc
    if not data.get("experimentId"):
        raise HTTPException(status_code=500, detail="experiment record missing experimentId")
    return ExperimentRecord(
        experimentId=str(data["experimentId"]),
        baselineFlowId=str(data.get("baselineFlowId") or ""),
        hypothesis=str(data.get("hypothesis") or ""),
        createdAt=str(data.get("createdAt") or ""),
        baselineVerdict=str(data.get("baselineVerdict") or "SKIPPED"),
        status=str(data.get("status") or "draft"),
        rungs=[RungModel(**r) for r in (data.get("rungs") or [])],
    )


class LawModel(BaseModel):
    lawId: str
    statement: str
    scope: str = "flow.topology"
    kind: str = "unknown"
    origin: str = "unknown"
    evidence: dict[str, Any] = {}
    confidence: float = 0.0
    status: str = "candidate"
    recordedAt: str = ""
    source: str = "engine"
    predicate: dict[str, Any] | None = None


def _registry_path() -> Path:
    """Law registry resolution: workspace .oiw/ first, then the committed
    packages/law-registry/ default (so a fresh workspace still shows the
    repo's ratified laws)."""
    ws = os.environ.get("OIW_WORKSPACE")
    if ws:
        p = Path(ws) / ".oiw" / "tenant-laws.yaml"
        if p.is_file():
            return p
    cli_root = Path(__file__).resolve().parents[4]
    committed = cli_root / "packages" / "law-registry" / "tenant-laws.yaml"
    if committed.is_file():
        return committed
    return Path(".oiw") / "tenant-laws.yaml"


@router.get("/laws", response_model=list[LawModel])
def list_laws(status: str | None = None, scope: str | None = None) -> list[LawModel]:
    """List the tenant-law registry (engine + manual laws).

    Only RATIFIED laws are enforced (validate OIW-W013 + assembler
    placement). Ratification is a CLI operator action — read-only here.
    """
    path = _registry_path()
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: list[LawModel] = []
    for law in data.get("laws") or []:
        model = LawModel(
            lawId=str(law.get("lawId") or ""),
            statement=str(law.get("statement") or ""),
            scope=str(law.get("scope") or "flow.topology"),
            kind=str(law.get("kind") or "unknown"),
            origin=str(law.get("origin") or "unknown"),
            evidence=dict(law.get("evidence") or {}),
            confidence=float(law.get("confidence") or 0.0),
            status=str(law.get("status") or "candidate"),
            recordedAt=str(law.get("recordedAt") or ""),
            source=str(law.get("source") or "engine"),
            predicate=law.get("predicate") or None,
        )
        if status and model.status != status:
            continue
        if scope and model.scope != scope:
            continue
        out.append(model)
    return out


__all__ = ["router"]
