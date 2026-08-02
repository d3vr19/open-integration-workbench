"""Shared fixtures for agent pipeline tests (WP-04)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "order-to-s4"


@pytest.fixture()
def temp_project(tmp_path: Path):
    """Copy order-to-s4 to a temp dir and init git so HEAD is real.

    Yields the Path to the temp project root (the parent containing
    the `order-to-s4` directory).
    """
    dest = tmp_path / "order-to-s4"
    shutil.copytree(EXAMPLE, dest)
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(["git", "-C", str(dest), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(dest), "commit", "-q", "-m", "test fixture"],
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
        check=True,
    )
    old_workspace = os.environ.get("OIW_WORKSPACE")
    os.environ["OIW_WORKSPACE"] = str(tmp_path)
    try:
        yield tmp_path
    finally:
        if old_workspace is not None:
            os.environ["OIW_WORKSPACE"] = old_workspace
        else:
            os.environ.pop("OIW_WORKSPACE", None)


@pytest.fixture()
def head_sha(temp_project: Path) -> str:
    """Short HEAD sha of the temp project's git repo."""
    return subprocess.run(
        ["git", "-C", str(temp_project / "order-to-s4"), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
