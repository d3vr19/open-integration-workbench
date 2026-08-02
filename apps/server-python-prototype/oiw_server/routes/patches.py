"""Patch route — typed patch operations on flows.

Spec ref: §12.5 (Typed Patch Format), §12.1 (all mutations go through typed patches).
"""

from __future__ import annotations

import subprocess

from fastapi import APIRouter, HTTPException
from oiw.patch import PatchError, apply_patch, write_flow
from pydantic import BaseModel

from ..workspace import load_project

router = APIRouter(prefix="/api/v1", tags=["Flows"])


class PatchOperation(BaseModel):
    op: str
    node: dict | None = None
    node_id: str | None = None
    from_: str | None = None
    to: str | None = None
    condition: str | None = None
    config: dict | None = None
    merge: bool | None = None
    position: dict | None = None


class PatchRequest(BaseModel):
    # WP-04 Task 6: baseRevision is now REQUIRED. Missing or stale
    # revision raises HTTP 409 Conflict.
    base_revision: str
    operations: list[dict]


class PatchResponse(BaseModel):
    applied: int
    new_revision: str | None
    flow_id: str


@router.patch("/projects/{project_id}/flows/{flow_id}", response_model=PatchResponse)
def patch_flow(project_id: str, flow_id: str, req: PatchRequest) -> PatchResponse:
    """Apply typed patch operations to a flow.

    Spec §12.5: validates base revision, applies operations, writes
    flow.yaml + diagram.json back to disk.

    WP-04 Task 6: baseRevision is REQUIRED. Returns 409 Conflict when
    missing or stale (i.e. client revision != current HEAD).
    """
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc
    try:
        flow = project.get_flow(flow_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"flow not found: {exc}") from exc

    # Get current HEAD revision for base-revision validation
    current_revision = _git_head_sha(project.root)

    # WP-04 Task 6: explicit conflict check (in addition to apply_patch's
    # own check) so we can return a structured 409 body.
    if req.base_revision != current_revision:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "BASE_REVISION_CONFLICT",
                "message": (
                    f"baseRevision {req.base_revision} != HEAD {current_revision}. "
                    "Re-fetch the flow and retry."
                ),
                "clientRevision": req.base_revision,
                "serverRevision": current_revision,
            },
        )

    try:
        result = apply_patch(
            flow=flow,
            operations=req.operations,
            base_revision=req.base_revision,
            current_revision=current_revision,
        )
        write_flow(flow)
    except PatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Re-read the new HEAD sha after write (the working tree is dirty but
    # not yet committed — the client sees the same sha until a commit happens)
    return PatchResponse(
        applied=result.operations_applied,
        new_revision=current_revision,
        flow_id=flow.id,
    )


def _git_head_sha(root) -> str:
    """Get the short HEAD sha of the project's git repo."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"
