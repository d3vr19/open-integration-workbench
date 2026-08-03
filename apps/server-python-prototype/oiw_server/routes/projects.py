"""Project routes. Spec §21.1."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models import FlowSummary, ProjectSummary
from ..workspace import discover_projects, load_project

router = APIRouter(prefix="/api/v1", tags=["Projects"])


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects() -> list[ProjectSummary]:
    out: list[ProjectSummary] = []
    for path in discover_projects():
        try:
            project = load_project(path.name)
        except Exception:
            continue
        # The API uses the directory name as the project ID for URL routing
        # (filesystem identity). The metadata.id from oiw.yaml is returned
        # inside the project manifest on GET /projects/{id}.
        out.append(
            ProjectSummary(
                id=path.name,
                name=project.name,
                path=str(path),
                created=project.created,
                flow_count=len(project.flows),
                test_count=len(project.tests),
            )
        )
    return out


@router.get("/projects/{project_id}")
def get_project(project_id: str) -> dict:
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc
    flows = [
        FlowSummary(
            id=f.id,
            name=f.name,
            version=f.version,
            node_count=len(f.nodes),
            test_count=sum(1 for t in project.tests if t.flow == f.id),
            labels=f.labels,
        )
        for f in project.flows
    ]
    return {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationProject",
        "metadata": {
            "id": project.id,
            "name": project.name,
            "created": project.created,
            "description": project.description,
            "labels": project.labels,
        },
        "spec": project.spec,
        "flows": [f.model_dump() for f in flows],
        "environments": [
            {
                "name": e.name,
                "target": e.target,
                "tenantUrl": e.tenant_url,
            }
            for e in project.environments
        ],
    }
