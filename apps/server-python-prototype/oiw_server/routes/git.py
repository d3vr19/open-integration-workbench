"""Git route. Spec §21.1, §11."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from oiw.git_ops import git_status as _git_status

from ..models import GitStatus
from ..workspace import load_project

router = APIRouter(prefix="/api/v1", tags=["Git"])


@router.get("/projects/{project_id}/git/status", response_model=GitStatus)
def git_status_endpoint(project_id: str) -> GitStatus:
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc
    status = _git_status(project.root)
    return GitStatus(
        branch=status.branch,
        head_sha=status.head_sha,
        dirty=status.dirty,
        ahead=status.ahead,
        last_build_digest=status.last_build_digest,
        last_build_target=status.last_build_target,
    )
