"""End-to-end API tests for the OIW FastAPI prototype.

Spec ref: §21.1 (REST Endpoints). Tests the full API contract against the
reference scenarios.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXAMPLES = REPO_ROOT / "examples"


@pytest.fixture(scope="module", autouse=True)
def _workspace_env():
    """Point the server at the examples/ directory."""
    old = os.environ.get("OIW_WORKSPACE")
    os.environ["OIW_WORKSPACE"] = str(EXAMPLES)
    yield
    if old is not None:
        os.environ["OIW_WORKSPACE"] = old
    else:
        os.environ.pop("OIW_WORKSPACE", None)


@pytest.fixture(scope="module")
def client():
    from oiw_server.main import app

    return TestClient(app)


# ---------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


# ---------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------


def test_list_projects(client: TestClient) -> None:
    r = client.get("/api/v1/projects")
    assert r.status_code == 200
    projects = r.json()
    ids = [p["id"] for p in projects]
    assert "order-to-s4" in ids
    assert "sftp-order-drop" in ids


def test_get_project(client: TestClient) -> None:
    r = client.get("/api/v1/projects/order-to-s4")
    assert r.status_code == 200
    body = r.json()
    assert body["metadata"]["id"] == "customer-order-integration"
    assert len(body["flows"]) == 1
    assert body["flows"][0]["id"] == "order-to-s4"


def test_get_project_404(client: TestClient) -> None:
    r = client.get("/api/v1/projects/nonexistent")
    assert r.status_code == 404


# ---------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------


def test_list_flows(client: TestClient) -> None:
    r = client.get("/api/v1/projects/order-to-s4/flows")
    assert r.status_code == 200
    flows = r.json()
    assert len(flows) == 1
    assert flows[0]["id"] == "order-to-s4"
    assert flows[0]["node_count"] > 0


def test_get_flow(client: TestClient) -> None:
    r = client.get("/api/v1/projects/order-to-s4/flows/order-to-s4")
    assert r.status_code == 200
    body = r.json()
    assert body["metadata"]["id"] == "order-to-s4"
    assert len(body["spec"]["nodes"]) > 0
    assert len(body["spec"]["edges"]) > 0
    assert body["diagram"] is not None
    assert "nodes" in body["diagram"]


def test_get_flow_404(client: TestClient) -> None:
    r = client.get("/api/v1/projects/order-to-s4/flows/nonexistent")
    assert r.status_code == 404


# ---------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------


def test_validate_passes(client: TestClient) -> None:
    r = client.post("/api/v1/projects/order-to-s4/validate", json={"strict": True})
    assert r.status_code == 200
    body = r.json()
    assert body["passed"] is True
    assert body["error_count"] == 0


def test_validate_non_strict(client: TestClient) -> None:
    r = client.post("/api/v1/projects/order-to-s4/validate", json={"strict": False})
    assert r.status_code == 200
    body = r.json()
    assert body["error_count"] == 0


def test_validate_404(client: TestClient) -> None:
    r = client.post("/api/v1/projects/nonexistent/validate", json={})
    assert r.status_code == 404


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------


def test_run_tests(client: TestClient) -> None:
    r = client.post("/api/v1/projects/order-to-s4/tests:run", json={})
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 2
    assert all(t["passed"] for t in results)


def test_run_tests_single_flow(client: TestClient) -> None:
    r = client.post(
        "/api/v1/projects/order-to-s4/tests:run",
        json={"flow_id": "order-to-s4"},
    )
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 2


def test_run_tests_single_test(client: TestClient) -> None:
    r = client.post(
        "/api/v1/projects/order-to-s4/tests:run",
        json={"test_name": "happy-path"},
    )
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    assert results[0]["test_name"] == "happy-path"


# ---------------------------------------------------------------------
# Builds
# ---------------------------------------------------------------------


def test_build_artifact(client: TestClient) -> None:
    r = client.post(
        "/api/v1/projects/order-to-s4/builds",
        json={"target_profile": "sap-cloud-integration-2026-07"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["digest"].startswith("sha256:")
    assert body["target_profile"] == "sap-cloud-integration-2026-07"
    assert body["entry_count"] > 0


def test_build_undeclared_profile(client: TestClient) -> None:
    r = client.post(
        "/api/v1/projects/order-to-s4/builds",
        json={"target_profile": "undeclared-profile"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------


def test_git_status(client: TestClient) -> None:
    r = client.get("/api/v1/projects/order-to-s4/git/status")
    assert r.status_code == 200
    body = r.json()
    assert "branch" in body
    assert "head_sha" in body
    assert "dirty" in body


# ---------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------


def test_inspect_golden_fixture(client: TestClient) -> None:
    fixture = (
        REPO_ROOT / "packages" / "test-fixtures" / "minimal" / "https-content-modifier-http" / "source.zip"
    )
    if not fixture.exists():
        pytest.skip("golden fixture not generated")
    with fixture.open("rb") as f:
        r = client.post(
            "/api/v1/archive/inspect",
            files={"archive": ("source.zip", f, "application/zip")},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["entry_count"] >= 1
    assert body["digest"].startswith("sha256:")


def test_inspect_zip_bomb_rejected(client: TestClient) -> None:
    fixture = REPO_ROOT / "packages" / "test-fixtures" / "negative" / "zip-bomb.zip"
    if not fixture.exists():
        pytest.skip("negative fixture not generated")
    with fixture.open("rb") as f:
        r = client.post(
            "/api/v1/archive/inspect",
            files={"archive": ("zip-bomb.zip", f, "application/zip")},
        )
    assert r.status_code == 400


def test_inspect_path_traversal_rejected(client: TestClient) -> None:
    fixture = REPO_ROOT / "packages" / "test-fixtures" / "negative" / "path-traversal.zip"
    if not fixture.exists():
        pytest.skip("negative fixture not generated")
    with fixture.open("rb") as f:
        r = client.post(
            "/api/v1/archive/inspect",
            files={"archive": ("path-traversal.zip", f, "application/zip")},
        )
    assert r.status_code == 400


# ---------------------------------------------------------------------
# OpenAPI spec
# ---------------------------------------------------------------------


def test_openapi_json_available(client: TestClient) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["openapi"].startswith("3.")
    assert "paths" in spec
    assert "/api/v1/projects" in spec["paths"]
    # FastAPI generates snake_case path params; the authoritative OpenAPI
    # spec in packages/api-spec/openapi.yaml uses camelCase. Both are valid;
    # the contract is the path structure, not the param name.
    flow_path = "/api/v1/projects/{project_id}/flows/{flow_id}"
    assert flow_path in spec["paths"]


def test_swagger_ui_available(client: TestClient) -> None:
    r = client.get("/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower() or "openapi" in r.text.lower()
