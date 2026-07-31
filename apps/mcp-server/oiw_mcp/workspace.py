"""Workspace helpers — load projects by directory name."""

from __future__ import annotations

from oiw.project import Project, ProjectError

from .config import workspace_root


def load_project(project_id: str) -> Project:
    """Load a project by its directory name in the workspace."""
    root = workspace_root()
    candidate = root / project_id
    if not candidate.is_dir() or not (candidate / "oiw.yaml").exists():
        raise ProjectError(f"project not found: {project_id}")
    return Project.load(candidate)
