"""Tests for the agent pipeline.

Spec ref: §12.2 (Agent Pipeline), §21.1 (agents:plan, agents:implement).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "order-to-s4"


@pytest.fixture()
def temp_workspace(tmp_path: Path):
    """Copy example to a temp dir, init git so baseRevision validation works
    (WP-04 Task 6)."""
    import subprocess

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


# ---------------------------------------------------------------------
# Requirements Interpreter
# ---------------------------------------------------------------------


def test_interpret_create_flow() -> None:
    from oiw_server.agent import interpret_requirement

    result = interpret_requirement("Create a new flow from HTTP to SFTP")
    assert result.intent == "create-flow"
    assert result.source_protocol == "https"
    assert result.target_protocol == "sftp"


def test_interpret_add_validation() -> None:
    from oiw_server.agent import interpret_requirement

    result = interpret_requirement("Add validation to the order flow")
    assert result.intent == "add-validation"
    assert "validate" in result.operations


def test_interpret_add_test() -> None:
    from oiw_server.agent import interpret_requirement

    result = interpret_requirement("Add a test for the order-to-s4 flow")
    assert result.intent == "add-test"


def test_interpret_modify_flow() -> None:
    from oiw_server.agent import interpret_requirement

    result = interpret_requirement("Modify the flow to add routing")
    assert result.intent == "modify-flow"
    assert "route" in result.operations


def test_interpret_general() -> None:
    from oiw_server.agent import interpret_requirement

    result = interpret_requirement("Help me understand the integration")
    assert result.intent == "general"


def test_interpret_archetype_detection() -> None:
    from oiw_server.agent import interpret_requirement

    result = interpret_requirement("Create a flow from HTTP to SFTP with validation and transformation")
    assert result.archetype == "https-to-sftp"
    assert "validate" in result.operations
    assert "transform" in result.operations


# ---------------------------------------------------------------------
# Integration Planner
# ---------------------------------------------------------------------


def test_plan_create_flow_has_steps() -> None:
    from oiw_server.agent import interpret_requirement, plan_implementation

    req = interpret_requirement("Create a new flow")
    plan = plan_implementation(req, "test-project", "new-flow")
    assert len(plan.steps) > 0
    # Should include flow.patch, flow.validate, test.run
    tools = [s.tool for s in plan.steps]
    assert "flow.patch" in tools
    assert "flow.validate" in tools
    assert "test.run" in tools


def test_plan_add_validation_creates_resource() -> None:
    from oiw_server.agent import interpret_requirement, plan_implementation

    req = interpret_requirement("Add validation to the flow")
    plan = plan_implementation(req, "test-project", "order-to-s4")
    tools = [s.tool for s in plan.steps]
    assert "flow.patch" in tools
    assert "resource.write" in tools


def test_plan_add_test_creates_test_file() -> None:
    from oiw_server.agent import interpret_requirement, plan_implementation

    req = interpret_requirement("Add a test")
    plan = plan_implementation(req, "test-project", "order-to-s4")
    tools = [s.tool for s in plan.steps]
    assert "test.create" in tools


def test_plan_includes_assumptions_and_risks() -> None:
    from oiw_server.agent import interpret_requirement, plan_implementation

    req = interpret_requirement("Create a flow")
    plan = plan_implementation(req, "test-project")
    assert len(plan.assumptions) > 0


def test_plan_general_requirement_has_risk() -> None:
    from oiw_server.agent import interpret_requirement, plan_implementation

    req = interpret_requirement("Help me")
    plan = plan_implementation(req, "test-project")
    assert len(plan.risks) > 0


# ---------------------------------------------------------------------
# POST /agents:plan
# ---------------------------------------------------------------------


def test_plan_endpoint(temp_workspace, client: TestClient) -> None:
    r = client.post(
        "/api/v1/projects/order-to-s4/agents:plan",
        json={"requirement": "Add validation to the order flow", "flowId": "order-to-s4"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "requirement" in body
    assert "steps" in body
    assert len(body["steps"]) > 0
    assert body["requirement"]["intent"] == "add-validation"


def test_plan_endpoint_404(client: TestClient) -> None:
    r = client.post(
        "/api/v1/projects/nonexistent/agents:plan",
        json={"requirement": "test"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------
# POST /agents:implement
# ---------------------------------------------------------------------


def test_implement_dry_run(temp_workspace, client: TestClient) -> None:
    r = client.post(
        "/api/v1/projects/order-to-s4/agents:implement",
        json={
            "requirement": "Add validation to the order flow",
            "flowId": "order-to-s4",
            "dryRun": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "dry run" in body["errors"][0]
    assert len(body["stepResults"]) == 0


def test_implement_add_validation(temp_workspace, client: TestClient) -> None:
    """Actually execute the add-validation plan and verify the node is added."""
    r = client.post(
        "/api/v1/projects/order-to-s4/agents:implement",
        json={
            "requirement": "Add validation to the order flow",
            "flowId": "order-to-s4",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert len(body["stepResults"]) > 0

    # Verify the validator node was actually added
    r2 = client.get("/api/v1/projects/order-to-s4/flows/order-to-s4")
    assert r2.status_code == 200
    node_ids = [n["id"] for n in r2.json()["spec"]["nodes"]]
    assert "validate-input" in node_ids


def test_implement_add_test(temp_workspace, client: TestClient) -> None:
    """Actually execute the add-test plan and verify the test file is created."""
    r = client.post(
        "/api/v1/projects/order-to-s4/agents:implement",
        json={
            "requirement": "Add a test for the flow",
            "flowId": "order-to-s4",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True

    # Verify the test file was created by running tests (the new test should appear)
    r2 = client.post(
        "/api/v1/projects/order-to-s4/tests:run",
        json={"flowId": "order-to-s4"},
    )
    assert r2.status_code == 200
    test_names = [t["test_name"] for t in r2.json()]
    assert "agent-generated" in test_names


def test_implement_404(client: TestClient) -> None:
    r = client.post(
        "/api/v1/projects/nonexistent/agents:implement",
        json={"requirement": "test"},
    )
    assert r.status_code == 404


def test_implement_returns_trajectory_id(temp_workspace, client: TestClient) -> None:
    """OW-027: POST /agents:implement returns a trajectoryId.

    The trajectory ID should be a non-empty string starting with 'traj-'
    so the UI can link to `oiw trajectory show --id <id>`.
    """
    r = client.post(
        "/api/v1/projects/order-to-s4/agents:implement",
        json={
            "requirement": "Add validation to the order flow",
            "flowId": "order-to-s4",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "trajectoryId" in body
    assert body["trajectoryId"] is not None
    assert body["trajectoryId"].startswith("traj-")

    # Verify the trajectory file was persisted
    import os
    from pathlib import Path

    workspace = os.environ["OIW_WORKSPACE"]
    traj_dir = Path(workspace) / "order-to-s4" / ".oiw" / "trajectories"
    traj_files = list(traj_dir.glob("traj-*.yaml"))
    assert len(traj_files) >= 1
    # The trajectory ID in the response matches a persisted file
    assert any(f.name == f"{body['trajectoryId']}.yaml" for f in traj_files)


def test_implement_dry_run_returns_null_trajectory_id(temp_workspace, client: TestClient) -> None:
    """OW-027: dry run returns trajectoryId=None (no execution, no trajectory)."""
    r = client.post(
        "/api/v1/projects/order-to-s4/agents:implement",
        json={
            "requirement": "Add validation to the order flow",
            "flowId": "order-to-s4",
            "dryRun": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["trajectoryId"] is None
