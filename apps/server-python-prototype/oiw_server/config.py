"""Server configuration.

Spec ref: §18.5 (Environment Variables), §4.5 (Local-First and Offline-Capable).
"""

from __future__ import annotations

import os
from pathlib import Path


def workspace_root() -> Path:
    """Resolve the workspace root from OIW_WORKSPACE or default to examples/.

    The workspace is the directory the server scans for OIW projects.
    """
    env = os.environ.get("OIW_WORKSPACE")
    if env:
        return Path(env).resolve()
    # Default: repo root / examples
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    return (repo_root / "examples").resolve()


def server_version() -> str:
    from . import __version__

    return __version__
