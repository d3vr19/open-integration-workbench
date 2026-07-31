"""Flow routes. Spec §21.1."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models import FlowSummary
from ..workspace import load_project

router = APIRouter(prefix="/api/v1", tags=["Flows"])


@router.get("/projects/{project_id}/flows", response_model=list[FlowSummary])
def list_flows(project_id: str) -> list[FlowSummary]:
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc
    return [
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


@router.get("/projects/{project_id}/flows/{flow_id}")
def get_flow(project_id: str, flow_id: str) -> dict:
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc
    try:
        flow = project.get_flow(flow_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"flow not found: {exc}") from exc

    nodes = [{"id": n.id, "type": n.type, "config": n.config, "fidelity": n.fidelity} for n in flow.nodes]
    edges = [
        {"from": e.from_, "to": e.to, **({"condition": e.condition} if e.condition else {})}
        for e in flow.edges
    ]
    entrypoints = [
        {"id": e.id, "type": e.type, "config": e.config, "fidelity": e.fidelity} for e in flow.entrypoints
    ]
    spec: dict = {
        "entrypoints": entrypoints,
        "nodes": nodes,
        "edges": edges,
        "extensions": flow.extensions,
    }
    if flow.error_handling:
        spec["errorHandling"] = {
            "defaultExceptionSubprocess": {
                "steps": [
                    {"id": s.id, "type": s.type, "config": s.config, "fidelity": s.fidelity}
                    for s in flow.error_handling.steps
                ]
            }
        }
    return {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationFlow",
        "metadata": {
            "id": flow.id,
            "name": flow.name,
            "version": flow.version,
            "labels": flow.labels,
            **({"generatedBy": flow.generated_by} if flow.generated_by else {}),
        },
        "spec": spec,
        "diagram": flow.diagram,
    }
