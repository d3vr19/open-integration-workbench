"""Calibration routes — cached tenant-oracle reports (read-only).

WP-10 Track B-003 contract (spec landed before this route): serves the
`<project>/.oiw/calibration-*.yaml` files the `oiw tenant calibrate` loop
writes. Powers the local-trace vs tenant-MPL comparison view.

Honesty constraints baked in:
  - Reports are POINT-IN-TIME (blood law): `startedAt` is surfaced so the
    UI can bound the meaningful MPL epoch.
  - Read-only: calibrations are produced by the CLI oracle loop (tenant
    credentials + operator); never via this API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..workspace import find_project_path

router = APIRouter(prefix="/api/v1", tags=["Calibrations"])


def _resolve_project(project_id: str) -> Path:
    path = find_project_path(project_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    return Path(path)


class CalibrationSummary(BaseModel):
    artifactId: str
    packageId: str = ""
    finalStatus: str = ""
    messageSent: bool = False
    httpResponseStatus: int | None = None
    mplCompleted: int = 0
    mplFailed: int = 0
    rewardOverall: float | None = None
    startedAt: str = ""
    reportPath: str = ""


def _summarize(path: Path) -> CalibrationSummary:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cal = data.get("calibration") or {}
    reward = data.get("reward") or {}
    rows = cal.get("mplRows") or []
    statuses = [str(r.get("Status") or "") for r in rows]
    http_status = cal.get("httpResponseStatus")
    overall = reward.get("overall")
    return CalibrationSummary(
        artifactId=str(cal.get("artifactId") or path.stem.replace("calibration-", "")),
        packageId=str(cal.get("packageId") or ""),
        finalStatus=str(cal.get("finalStatus") or ""),
        messageSent=bool(cal.get("messageSent")),
        httpResponseStatus=int(http_status) if http_status is not None else None,
        mplCompleted=statuses.count("COMPLETED"),
        mplFailed=statuses.count("FAILED"),
        rewardOverall=float(overall) if overall is not None else None,
        startedAt=str(cal.get("startedAt") or ""),
        reportPath=path.name,
    )


@router.get("/projects/{project_id}/calibrations", response_model=list[CalibrationSummary])
def list_calibrations(project_id: str) -> list[CalibrationSummary]:
    """List cached calibration reports for a project (newest first)."""
    project_path = _resolve_project(project_id)
    cal_dir = Path(project_path) / ".oiw"
    if not cal_dir.is_dir():
        return []
    out = [
        _summarize(p)
        for p in sorted(cal_dir.glob("calibration-*.yaml"))
        # the smoke/restore runs are transient artifacts — list them all;
        # the UI labels by age (startedAt) rather than filtering here
    ]
    out.sort(key=lambda s: s.startedAt, reverse=True)
    return out


@router.get(
    "/projects/{project_id}/calibrations/{artifact_id}",
    response_model=dict[str, Any],
)
def get_calibration(project_id: str, artifact_id: str) -> dict[str, Any]:
    """Get one cached calibration report (full payload, calibration+reward)."""
    project_path = _resolve_project(project_id)
    cal_dir = Path(project_path) / ".oiw"
    if not cal_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"no calibration reports in project '{project_id}'",
        )
    # Primary naming: calibration-<artifactId>.yaml
    candidate = cal_dir / f"calibration-{artifact_id}.yaml"
    if not candidate.is_file():
        # A same-artifact suffix scan would be ambiguous — refuse loudly
        # rather than guessing (one artifact may have several campaign-era
        # reports; the LIST endpoint disambiguates by startedAt).
        raise HTTPException(
            status_code=404,
            detail=f"no calibration report for artifact '{artifact_id}' "
            f"in project '{project_id}' (see the list endpoint for available reports)",
        )
    try:
        data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=500, detail=f"corrupt calibration report: {exc}") from exc
    return data


__all__ = ["router"]
