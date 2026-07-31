"""MCP server configuration."""

from __future__ import annotations

import os
from pathlib import Path


def workspace_root() -> Path:
    """Resolve the workspace root from OIW_WORKSPACE or default to examples/."""
    env = os.environ.get("OIW_WORKSPACE")
    if env:
        return Path(env).resolve()
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    return (repo_root / "examples").resolve()
