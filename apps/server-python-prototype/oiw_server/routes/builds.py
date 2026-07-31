"""Builds route. Spec §21.1, §8."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from oiw.compiler.export import BuildError, build_artifact
from pydantic import BaseModel

from ..models import BuildResult
from ..workspace import load_project

router = APIRouter(prefix="/api/v1", tags=["Builds"])


class BuildRequest(BaseModel):
    target_profile: str


@router.post("/projects/{project_id}/builds", response_model=BuildResult)
def build_endpoint(project_id: str, req: BuildRequest) -> BuildResult:
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc
    try:
        result = build_artifact(project, req.target_profile, project.root / "dist")
    except BuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BuildResult(
        out_dir=str(result.out_dir),
        manifest_path=str(result.manifest_path),
        digest=result.digest,
        compiler_version=result.compiler_version,
        target_profile=result.target_profile,
        entry_count=len(result.entries),
    )
