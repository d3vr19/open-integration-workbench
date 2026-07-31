"""Workspace project discovery and caching.

Spec ref: §21.1 (GET /projects).
"""

from __future__ import annotations

from pathlib import Path

from oiw.project import Project, ProjectError

from .config import workspace_root


def discover_projects() -> list[Path]:
    """Scan the workspace root for directories containing oiw.yaml."""
    root = workspace_root()
    if not root.is_dir():
        return []
    projects: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "oiw.yaml").exists():
            projects.append(child)
    return projects


def load_project(project_id: str) -> Project:
    """Load a project by its ID (directory name in the workspace)."""
    root = workspace_root()
    candidate = root / project_id
    if not candidate.is_dir() or not (candidate / "oiw.yaml").exists():
        raise ProjectError(f"project not found: {project_id}")
    return Project.load(candidate)


def find_project_path(project_id: str) -> Path | None:
    """Return the path to a project, or None if not found."""
    root = workspace_root()
    candidate = root / project_id
    if candidate.is_dir() and (candidate / "oiw.yaml").exists():
        return candidate
    return None
