"""Tests for the PATCH /flows/{flowId} endpoint.

Uses a temp workspace so tests can mutate files without affecting the real
examples directory.
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
    """Copy order-to-s4 to a temp dir and point OIW_WORKSPACE at it."""
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


def test_patch_add_node(temp_workspace, client: TestClient) -> None:
    """Add a node via PATCH and verify it persists."""
    r = client.patch(
        "/api/v1/projects/order-to-s4/flows/order-to-s4",
        json={
            "operations": [
                {
                    "op": "addNode",
                    "node": {
                        "id": "api-added-node",
                        "type": "log.message",
                        "config": {"level": "INFO", "message": "via API"},
                        "fidelity": "compatible-subset",
                    },
                }
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] == 1
    assert body["flow_id"] == "order-to-s4"

    # Verify it's now in the flow
    r2 = client.get("/api/v1/projects/order-to-s4/flows/order-to-s4")
    assert r2.status_code == 200
    node_ids = [n["id"] for n in r2.json()["spec"]["nodes"]]
    assert "api-added-node" in node_ids


def test_patch_remove_node(temp_workspace, client: TestClient) -> None:
    """Add then remove a node via PATCH."""
    # Add
    client.patch(
        "/api/v1/projects/order-to-s4/flows/order-to-s4",
        json={"operations": [{"op": "addNode", "node": {"id": "to-remove", "type": "log.message"}}]},
    )
    # Remove
    r = client.patch(
        "/api/v1/projects/order-to-s4/flows/order-to-s4",
        json={"operations": [{"op": "removeNode", "nodeId": "to-remove"}]},
    )
    assert r.status_code == 200
    # Verify it's gone
    r2 = client.get("/api/v1/projects/order-to-s4/flows/order-to-s4")
    node_ids = [n["id"] for n in r2.json()["spec"]["nodes"]]
    assert "to-remove" not in node_ids


def test_patch_update_node_config(temp_workspace, client: TestClient) -> None:
    """Update a node's config via PATCH."""
    r = client.patch(
        "/api/v1/projects/order-to-s4/flows/order-to-s4",
        json={
            "operations": [
                {
                    "op": "updateNodeConfig",
                    "nodeId": "receiver-s4-eu",
                    "config": {"timeoutSeconds": 99},
                }
            ]
        },
    )
    assert r.status_code == 200
    # Verify the change persisted
    r2 = client.get("/api/v1/projects/order-to-s4/flows/order-to-s4")
    nodes = {n["id"]: n for n in r2.json()["spec"]["nodes"]}
    assert nodes["receiver-s4-eu"]["config"]["timeoutSeconds"] == 99
    # Other config keys preserved (merge)
    assert "url" in nodes["receiver-s4-eu"]["config"]


def test_patch_add_edge(temp_workspace, client: TestClient) -> None:
    """Add a node + edge via PATCH."""
    r = client.patch(
        "/api/v1/projects/order-to-s4/flows/order-to-s4",
        json={
            "operations": [
                {"op": "addNode", "node": {"id": "edge-target", "type": "log.message"}},
                {"op": "addEdge", "from": "transform", "to": "edge-target"},
            ]
        },
    )
    assert r.status_code == 200
    assert r.json()["applied"] == 2


def test_patch_move_node(temp_workspace, client: TestClient) -> None:
    """Move a node's position via PATCH."""
    r = client.patch(
        "/api/v1/projects/order-to-s4/flows/order-to-s4",
        json={
            "operations": [
                {
                    "op": "moveNode",
                    "nodeId": "transform",
                    "position": {"x": 123, "y": 456},
                }
            ]
        },
    )
    assert r.status_code == 200
    # Verify the position persisted
    r2 = client.get("/api/v1/projects/order-to-s4/flows/order-to-s4")
    diagram = r2.json().get("diagram")
    assert diagram is not None
    dn = next(n for n in diagram["nodes"] if n["id"] == "transform")
    assert dn["position"] == {"x": 123, "y": 456}


def test_patch_multiple_operations(temp_workspace, client: TestClient) -> None:
    """Apply multiple operations in a single PATCH."""
    r = client.patch(
        "/api/v1/projects/order-to-s4/flows/order-to-s4",
        json={
            "operations": [
                {"op": "addNode", "node": {"id": "multi-1", "type": "log.message"}},
                {"op": "addNode", "node": {"id": "multi-2", "type": "log.message"}},
                {"op": "addEdge", "from": "multi-1", "to": "multi-2"},
                {"op": "moveNode", "nodeId": "multi-1", "position": {"x": 10, "y": 20}},
            ]
        },
    )
    assert r.status_code == 200
    assert r.json()["applied"] == 4


def test_patch_invalid_operation_returns_400(temp_workspace, client: TestClient) -> None:
    """An invalid patch operation returns 400."""
    r = client.patch(
        "/api/v1/projects/order-to-s4/flows/order-to-s4",
        json={
            "operations": [
                {"op": "addNode", "node": {"id": "transform"}}  # duplicate ID
            ]
        },
    )
    assert r.status_code == 400


def test_patch_unknown_operation_returns_400(temp_workspace, client: TestClient) -> None:
    """An unknown operation type returns 400."""
    r = client.patch(
        "/api/v1/projects/order-to-s4/flows/order-to-s4",
        json={"operations": [{"op": "doMagic"}]},
    )
    assert r.status_code == 400


def test_patch_cycle_rejected(temp_workspace, client: TestClient) -> None:
    """A patch that introduces a cycle returns 400."""
    r = client.patch(
        "/api/v1/projects/order-to-s4/flows/order-to-s4",
        json={"operations": [{"op": "addEdge", "from": "route-by-region", "to": "transform"}]},
    )
    assert r.status_code == 400


def test_patch_404_unknown_project(client: TestClient) -> None:
    r = client.patch(
        "/api/v1/projects/nonexistent/flows/x",
        json={"operations": []},
    )
    assert r.status_code == 404


def test_patch_404_unknown_flow(temp_workspace, client: TestClient) -> None:
    r = client.patch(
        "/api/v1/projects/order-to-s4/flows/nonexistent",
        json={"operations": []},
    )
    assert r.status_code == 404


def test_patch_empty_operations(temp_workspace, client: TestClient) -> None:
    """An empty operations list is a no-op."""
    r = client.patch(
        "/api/v1/projects/order-to-s4/flows/order-to-s4",
        json={"operations": []},
    )
    assert r.status_code == 200
    assert r.json()["applied"] == 0
