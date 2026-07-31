"""Resource routes — read and write resource files (Groovy, XSLT, JSON Schema, etc.).

Spec ref: §6.1 (Monaco Editor for Groovy, XML, XSLT, JSON, YAML, properties),
§10.3 (Component Architecture — editors/), §11.1 (resources/ directory).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..workspace import load_project

router = APIRouter(prefix="/api/v1", tags=["Resources"])


# File extension → language ID for Monaco
_LANGUAGE_MAP = {
    ".groovy": "groovy",
    ".java": "java",
    ".xsl": "xml",
    ".xslt": "xml",
    ".xsd": "xml",
    ".xml": "xml",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".properties": "ini",
    ".py": "python",
    ".sh": "shell",
}


# Resource type classification (spec §12.4 resource.write tool)
_RESOURCE_TYPES = {
    ".groovy": "groovy",
    ".xsl": "xslt",
    ".xslt": "xslt",
    ".xsd": "xsd",
    ".json": "json-schema",
    ".wsdl": "wsdl",
    ".properties": "properties",
}


class ResourceSummary(BaseModel):
    path: str
    name: str
    resource_type: str
    language: str
    size: int


class ResourceContent(BaseModel):
    path: str
    content: str
    language: str
    resource_type: str
    size: int


class ResourceWriteRequest(BaseModel):
    content: str


@router.get("/projects/{project_id}/resources", response_model=list[ResourceSummary])
def list_resources(project_id: str) -> list[ResourceSummary]:
    """List all resource files in a project.

    Spec §11.1: resources live under flows/<flow>/resources/.
    """
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc

    out: list[ResourceSummary] = []
    flows_dir = project.root / "flows"
    if not flows_dir.is_dir():
        return out
    for flow_dir in sorted(flows_dir.iterdir()):
        if not flow_dir.is_dir():
            continue
        res_dir = flow_dir / "resources"
        if not res_dir.is_dir():
            continue
        for path in sorted(res_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(project.root).as_posix()
            ext = path.suffix.lower()
            out.append(
                ResourceSummary(
                    path=rel,
                    name=path.name,
                    resource_type=_RESOURCE_TYPES.get(ext, "unknown"),
                    language=_LANGUAGE_MAP.get(ext, "plaintext"),
                    size=path.stat().st_size,
                )
            )
    return out


@router.get("/projects/{project_id}/resources/{resource_path:path}", response_model=ResourceContent)
def get_resource(project_id: str, resource_path: str) -> ResourceContent:
    """Read a resource file.

    Path traversal is prevented by resolving and checking the path is within
    the project root.
    """
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc

    full_path = _resolve_resource_path(project.root, resource_path)
    if full_path is None or not full_path.is_file():
        raise HTTPException(status_code=404, detail=f"resource not found: {resource_path}")

    content = full_path.read_text(encoding="utf-8", errors="replace")
    ext = full_path.suffix.lower()
    return ResourceContent(
        path=resource_path,
        content=content,
        language=_LANGUAGE_MAP.get(ext, "plaintext"),
        resource_type=_RESOURCE_TYPES.get(ext, "unknown"),
        size=len(content.encode("utf-8")),
    )


@router.put("/projects/{project_id}/resources/{resource_path:path}", response_model=ResourceContent)
def write_resource(project_id: str, resource_path: str, req: ResourceWriteRequest) -> ResourceContent:
    """Write (create or update) a resource file.

    Spec §12.4 (resource.write MCP tool), §11.1 (resources/ directory).
    Path traversal is prevented.
    """
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc

    full_path = _resolve_resource_path(project.root, resource_path)
    if full_path is None:
        raise HTTPException(status_code=400, detail=f"invalid resource path: {resource_path}")

    # Only allow writing under flows/*/resources/
    try:
        rel = full_path.relative_to(project.root)
    except ValueError:
        raise HTTPException(status_code=400, detail="resource path escapes project root") from None

    parts = rel.parts
    if len(parts) < 3 or parts[0] != "flows" or parts[2] != "resources":
        raise HTTPException(
            status_code=400,
            detail="resource must be under flows/<flow>/resources/",
        )

    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(req.content, encoding="utf-8")
    ext = full_path.suffix.lower()
    return ResourceContent(
        path=resource_path,
        content=req.content,
        language=_LANGUAGE_MAP.get(ext, "plaintext"),
        resource_type=_RESOURCE_TYPES.get(ext, "unknown"),
        size=len(req.content.encode("utf-8")),
    )


def _resolve_resource_path(project_root: Path, resource_path: str) -> Path | None:
    """Resolve a resource path safely, preventing path traversal."""
    # Normalize and check for traversal
    normalized = resource_path.replace("\\", "/").lstrip("/")
    if ".." in normalized.split("/"):
        return None
    if normalized.startswith("/"):
        return None
    candidate = (project_root / normalized).resolve()
    # Verify the resolved path is within the project root
    try:
        candidate.relative_to(project_root.resolve())
    except ValueError:
        return None
    return candidate
