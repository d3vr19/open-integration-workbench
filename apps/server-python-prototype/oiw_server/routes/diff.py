"""Diff route — semantic diff between revisions.

Spec ref: §10.5 (Semantic Diff), §21.1 (GET /projects/{id}/diff).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from oiw.diff import structured_diff
from pydantic import BaseModel

from ..workspace import load_project

router = APIRouter(prefix="/api/v1", tags=["Git"])


class DiffResponse(BaseModel):
    base_sha: str
    head_sha: str
    total_changes: int
    flows: dict
    resources: dict
    tests: dict
    other: list[dict]


@router.get("/projects/{project_id}/diff", response_model=DiffResponse)
def get_diff(
    project_id: str,
    rev: str = "HEAD~1",
) -> DiffResponse:
    """Get a structured semantic diff between `rev` and HEAD.

    Spec §10.5: returns categorized changes (flows/resources/tests
    added/modified/removed + other) with base and head SHAs.
    """
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc

    diff = structured_diff(project.root, rev)
    data = diff.to_dict()
    return DiffResponse(**data)
