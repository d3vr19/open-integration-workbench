"""Tests for the diff endpoint.

Spec ref: §10.5 (Semantic Diff), §21.1 (GET /projects/{id}/diff).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "order-to-s4"


@pytest.fixture()
def temp_workspace(tmp_path: Path):
    """Copy order-to-s4 to a temp dir, init a git repo, make 2 commits."""
    dest = tmp_path / "order-to-s4"
    shutil.copytree(EXAMPLE, dest)

    # Init git repo and make an initial commit
    subprocess.run(["git", "init"], cwd=dest, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=dest, capture_output=True, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=dest, capture_output=True, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=dest,
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00",
        },
    )

    # Make a change — add a new resource file
    new_file = dest / "flows" / "order-to-s4" / "resources" / "scripts" / "newScript.groovy"
    new_file.write_text("// new script\nmessage.setProperty('test', 'true')\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=dest, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add new script"],
        cwd=dest,
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_DATE": "2026-01-02T00:00:00",
            "GIT_COMMITTER_DATE": "2026-01-02T00:00:00",
        },
    )

    old = os.environ.get("OIW_WORKSPACE")
    os.environ["OIW_WORKSPACE"] = str(tmp_path)
    yield
    if old is not None:
        os.environ["OIW_WORKSPACE"] = old
    else:
        os.environ.pop("OIW_WORKSPACE", None)


@pytest.fixture()
def client():
    from oiw_server.main import app

    return TestClient(app)


def test_diff_returns_structure(temp_workspace, client: TestClient) -> None:
    r = client.get("/api/v1/projects/order-to-s4/diff", params={"rev": "HEAD~1"})
    assert r.status_code == 200
    body = r.json()
    assert "base_sha" in body
    assert "head_sha" in body
    assert "total_changes" in body
    assert "flows" in body
    assert "resources" in body
    assert "tests" in body
    assert "other" in body


def test_diff_detects_added_resource(temp_workspace, client: TestClient) -> None:
    """The new script added in the second commit should appear in resources.added."""
    r = client.get("/api/v1/projects/order-to-s4/diff", params={"rev": "HEAD~1"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_changes"] > 0
    added = body["resources"]["added"]
    assert any("newScript.groovy" in p for p in added), f"newScript.groovy not in {added}"


def test_diff_shas_differ(temp_workspace, client: TestClient) -> None:
    r = client.get("/api/v1/projects/order-to-s4/diff", params={"rev": "HEAD~1"})
    body = r.json()
    assert body["base_sha"] != body["head_sha"]


def test_diff_no_changes(temp_workspace, client: TestClient) -> None:
    """Diffing HEAD against HEAD should show zero changes."""
    r = client.get("/api/v1/projects/order-to-s4/diff", params={"rev": "HEAD"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_changes"] == 0


def test_diff_404_unknown_project(client: TestClient) -> None:
    r = client.get("/api/v1/projects/nonexistent/diff")
    assert r.status_code == 404


def test_diff_flows_modified_structure(temp_workspace, client: TestClient) -> None:
    """The diff response should have the correct flows structure."""
    r = client.get("/api/v1/projects/order-to-s4/diff", params={"rev": "HEAD~1"})
    body = r.json()
    flows = body["flows"]
    assert "added" in flows
    assert "modified" in flows
    assert "removed" in flows
    assert isinstance(flows["added"], list)
    assert isinstance(flows["modified"], list)
    assert isinstance(flows["removed"], list)
