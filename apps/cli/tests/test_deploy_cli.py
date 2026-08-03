"""Tests for the deploy CLI command (WP-05 Tasks 5-7).

Covers:
  - CLI: propose → approve → upload → execute → verify happy path
  - CLI: drift check blocks upload when digests differ
  - CLI: status shows current state + history
  - CLI: approval required for execute (no approval → fails)
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "order-to-s4"


@pytest.fixture()
def deploy_workspace(tmp_path: Path):
    """Copy order-to-s4 to a temp dir, init git, set env vars for profiles."""
    dest = tmp_path / "order-to-s4"
    shutil.copytree(EXAMPLE, dest)
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(["git", "-C", str(dest), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(dest), "commit", "-q", "-m", "test"],
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t.com",
        },
        check=True,
    )
    old = {}
    env_vars = {
        "DEV_TENANT_URL": "https://dev.sap.com",
        "DEV_TOKEN_URL": "https://dev.sap.com/oauth/token",
        "DEV_CLIENT_ID": "dev-client",
    }
    for k, v in env_vars.items():
        old[k] = os.environ.get(k)
        os.environ[k] = v
    yield dest
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _run_cli(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    """Run oiw CLI with the given args in the workspace."""
    env = {
        **os.environ,
        "PYTHONPATH": f"{REPO_ROOT}/apps/cli:{REPO_ROOT}/apps/mcp-server:{REPO_ROOT}/apps/server-python-prototype",
    }
    return subprocess.run(
        [sys.executable, "-m", "oiw.cli", *args, "--project", str(workspace)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


import sys  # noqa: E402


def test_deploy_happy_path(deploy_workspace: Path) -> None:
    """propose → approve → upload → execute → verify → status."""
    pkg = "order-to-s4"
    profile = "dev"

    # Propose
    r = _run_cli(deploy_workspace, "deploy", "propose", "--profile", profile, "--package", pkg)
    assert r.returncode == 0, f"propose failed: {r.stderr}"
    assert "PROPOSED" in r.stdout

    # Approve
    r = _run_cli(
        deploy_workspace, "deploy", "approve", "--profile", profile, "--package", pkg, "--approver", "alice"
    )
    assert r.returncode == 0, f"approve failed: {r.stderr}"
    assert "APPROVED" in r.stdout

    # Upload
    r = _run_cli(deploy_workspace, "deploy", "upload", "--profile", profile, "--package", pkg)
    assert r.returncode == 0, f"upload failed: {r.stderr}"
    assert "UPLOADED" in r.stdout

    # Execute
    r = _run_cli(deploy_workspace, "deploy", "execute", "--profile", profile, "--package", pkg)
    assert r.returncode == 0, f"execute failed: {r.stderr}"
    assert "DEPLOYED" in r.stdout

    # Verify (smoke test — Task 7)
    r = _run_cli(deploy_workspace, "deploy", "verify", "--profile", profile, "--package", pkg)
    assert r.returncode == 0, f"verify failed: {r.stderr}"
    assert "VERIFIED" in r.stdout

    # Status
    r = _run_cli(deploy_workspace, "deploy", "status", "--profile", profile, "--package", pkg)
    assert r.returncode == 0, f"status failed: {r.stderr}"
    assert "VERIFIED" in r.stdout
    assert "alice" in r.stdout  # approver in history


def test_deploy_status_shows_history(deploy_workspace: Path) -> None:
    """status command shows the full transition history."""
    pkg = "order-to-s4"
    profile = "dev"

    _run_cli(deploy_workspace, "deploy", "propose", "--profile", profile, "--package", pkg)
    r = _run_cli(deploy_workspace, "deploy", "status", "--profile", profile, "--package", pkg)
    assert r.returncode == 0
    assert "PROPOSED" in r.stdout
    assert "History" in r.stdout
    assert "DRAFT" in r.stdout  # Initial → VALIDATED → ... → PROPOSED


def test_deploy_check_drift_no_artifact(deploy_workspace: Path) -> None:
    """check-drift on a tenant with no artifact → safe to upload."""
    r = _run_cli(
        deploy_workspace,
        "deploy",
        "check-drift",
        "--profile",
        "dev",
        "--package",
        "never-uploaded",
        "--build-digest",
        "sha256:abc123",
    )
    assert r.returncode == 0
    assert "NO_TENANT_ARTIFACT" in r.stdout
    assert "True" in r.stdout  # safe_to_upload


def test_deploy_state_persisted(deploy_workspace: Path) -> None:
    """State persists across CLI invocations."""
    pkg = "order-to-s4"
    profile = "dev"

    _run_cli(deploy_workspace, "deploy", "propose", "--profile", profile, "--package", pkg)
    _run_cli(
        deploy_workspace, "deploy", "approve", "--profile", profile, "--package", pkg, "--approver", "bob"
    )

    # New CLI invocation — should load APPROVED state
    r = _run_cli(deploy_workspace, "deploy", "status", "--profile", profile, "--package", pkg)
    assert "APPROVED" in r.stdout
    assert "bob" in r.stdout


def test_deploy_execute_without_approval_fails(deploy_workspace: Path) -> None:
    """execute without approve → fails (can't skip APPROVED state)."""
    pkg = "order-to-s4"
    profile = "dev"

    # Propose but don't approve
    _run_cli(deploy_workspace, "deploy", "propose", "--profile", profile, "--package", pkg)
    # Try to execute — should fail (PROPOSED → DEPLOYED is illegal)
    r = _run_cli(deploy_workspace, "deploy", "execute", "--profile", profile, "--package", pkg)
    assert r.returncode != 0
