"""Tests for the resource read/write endpoints.

Spec ref: §6.1 (Monaco Editor), §10.3 (editors/), §11.1 (resources/), §12.4 (resource.write).
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
    dest = tmp_path / "order-to-s4"
    shutil.copytree(EXAMPLE, dest)
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
# GET /resources (list)
# ---------------------------------------------------------------------


def test_list_resources(temp_workspace, client: TestClient) -> None:
    r = client.get("/api/v1/projects/order-to-s4/resources")
    assert r.status_code == 200
    resources = r.json()
    assert len(resources) > 0
    paths = [res["path"] for res in resources]
    # The order-to-s4 example has a schema, a script, and an XSLT
    assert any("order.schema.json" in p for p in paths)
    assert any("normalizeOrder.groovy" in p for p in paths)
    assert any("order.xsl" in p for p in paths)


def test_list_resources_includes_language(temp_workspace, client: TestClient) -> None:
    r = client.get("/api/v1/projects/order-to-s4/resources")
    resources = r.json()
    for res in resources:
        assert "language" in res
        assert "resource_type" in res
        assert res["language"] != "plaintext" or res["resource_type"] == "unknown"


def test_list_resources_404_unknown_project(client: TestClient) -> None:
    r = client.get("/api/v1/projects/nonexistent/resources")
    assert r.status_code == 404


# ---------------------------------------------------------------------
# GET /resources/{path} (read)
# ---------------------------------------------------------------------


def test_get_resource_groovy(temp_workspace, client: TestClient) -> None:
    r = client.get(
        "/api/v1/projects/order-to-s4/resources/flows/order-to-s4/resources/scripts/normalizeOrder.groovy"
    )
    assert r.status_code == 200
    body = r.json()
    assert "message" in body["content"]
    assert body["language"] == "groovy"
    assert body["resource_type"] == "groovy"
    assert body["size"] > 0


def test_get_resource_json_schema(temp_workspace, client: TestClient) -> None:
    r = client.get(
        "/api/v1/projects/order-to-s4/resources/flows/order-to-s4/resources/schemas/order.schema.json"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["language"] == "json"
    assert body["resource_type"] == "json-schema"
    assert '"orderId"' in body["content"]


def test_get_resource_xslt(temp_workspace, client: TestClient) -> None:
    r = client.get("/api/v1/projects/order-to-s4/resources/flows/order-to-s4/resources/mappings/order.xsl")
    assert r.status_code == 200
    body = r.json()
    assert body["language"] == "xml"
    assert body["resource_type"] == "xslt"
    assert "<xsl:stylesheet" in body["content"]


def test_get_resource_404_not_found(temp_workspace, client: TestClient) -> None:
    r = client.get("/api/v1/projects/order-to-s4/resources/nonexistent.txt")
    assert r.status_code == 404


def test_get_resource_path_traversal_rejected(temp_workspace, client: TestClient) -> None:
    """Path traversal attempts must return 404 (not 200 with file contents)."""
    r = client.get("/api/v1/projects/order-to-s4/resources/../../../etc/passwd")
    assert r.status_code in (404, 400)


# ---------------------------------------------------------------------
# PUT /resources/{path} (write)
# ---------------------------------------------------------------------


def test_write_resource_creates_new_file(temp_workspace, client: TestClient) -> None:
    new_content = "// new script\nmessage.setProperty('test', 'true')\n"
    r = client.put(
        "/api/v1/projects/order-to-s4/resources/flows/order-to-s4/resources/scripts/newScript.groovy",
        json={"content": new_content},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == new_content
    assert body["language"] == "groovy"

    # Verify it's on disk
    r2 = client.get(
        "/api/v1/projects/order-to-s4/resources/flows/order-to-s4/resources/scripts/newScript.groovy"
    )
    assert r2.status_code == 200
    assert r2.json()["content"] == new_content


def test_write_resource_overwrites_existing(temp_workspace, client: TestClient) -> None:
    # Read existing
    r = client.get(
        "/api/v1/projects/order-to-s4/resources/flows/order-to-s4/resources/scripts/normalizeOrder.groovy"
    )
    original = r.json()["content"]
    # Modify
    modified = original + "\n// added by test\n"
    r2 = client.put(
        "/api/v1/projects/order-to-s4/resources/flows/order-to-s4/resources/scripts/normalizeOrder.groovy",
        json={"content": modified},
    )
    assert r2.status_code == 200
    # Re-read
    r3 = client.get(
        "/api/v1/projects/order-to-s4/resources/flows/order-to-s4/resources/scripts/normalizeOrder.groovy"
    )
    assert r3.json()["content"] == modified


def test_write_resource_rejects_path_outside_resources(temp_workspace, client: TestClient) -> None:
    """Writing outside flows/*/resources/ must be rejected."""
    r = client.put(
        "/api/v1/projects/order-to-s4/resources/flows/order-to-s4/flow.yaml",
        json={"content": "malicious"},
    )
    assert r.status_code == 400


def test_write_resource_rejects_path_traversal(temp_workspace, client: TestClient) -> None:
    """Path traversal must be rejected."""
    r = client.put(
        "/api/v1/projects/order-to-s4/resources/../../../etc/evil.txt",
        json={"content": "malicious"},
    )
    assert r.status_code in (400, 404)


def test_write_resource_creates_parent_dirs(temp_workspace, client: TestClient) -> None:
    """Writing to a path with non-existent parent directories should create them."""
    r = client.put(
        "/api/v1/projects/order-to-s4/resources/flows/order-to-s4/resources/mappings/sub/deep.xsl",
        json={"content": "<xsl:stylesheet version='1.0'/>"},
    )
    assert r.status_code == 200
