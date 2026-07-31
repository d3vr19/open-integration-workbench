"""Tests for the typed patch module (spec §12.5)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from oiw.patch import PatchError, apply_patch, write_flow
from oiw.project import IntegrationFlow, Project

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "order-to-s4"


@pytest.fixture()
def temp_project(tmp_path: Path) -> Project:
    """Copy the order-to-s4 example to a temp dir so we can mutate it safely."""
    dest = tmp_path / "order-to-s4"
    shutil.copytree(EXAMPLE, dest)
    return Project.load(dest)


def _get_flow(project: Project) -> IntegrationFlow:
    return project.get_flow("order-to-s4")


# ---------------------------------------------------------------------
# addNode
# ---------------------------------------------------------------------


def test_add_node(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    original_count = len(flow.nodes)
    apply_patch(
        flow,
        [
            {
                "op": "addNode",
                "node": {
                    "id": "new-log",
                    "type": "log.message",
                    "config": {"level": "INFO", "message": "new node"},
                    "fidelity": "compatible-subset",
                },
            }
        ],
    )
    assert len(flow.nodes) == original_count + 1
    assert any(n.id == "new-log" for n in flow.nodes)


def test_add_node_duplicate_rejected(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    existing_id = flow.nodes[0].id
    with pytest.raises(PatchError, match="duplicate"):
        apply_patch(flow, [{"op": "addNode", "node": {"id": existing_id, "type": "log.message"}}])


def test_add_node_with_position(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    assert flow.diagram is not None
    original_diagram_count = len(flow.diagram.get("nodes", []))
    apply_patch(
        flow,
        [
            {
                "op": "addNode",
                "node": {"id": "new-node", "type": "log.message"},
                "position": {"x": 100, "y": 200},
            }
        ],
    )
    assert len(flow.diagram["nodes"]) == original_diagram_count + 1
    new_dn = flow.diagram["nodes"][-1]
    assert new_dn["id"] == "new-node"
    assert new_dn["position"] == {"x": 100, "y": 200}


# ---------------------------------------------------------------------
# removeNode
# ---------------------------------------------------------------------


def test_remove_node(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    # Find a non-entrypoint, non-critical node to remove
    # 'log-error' is in the error subprocess, not in the main flow
    # Let's add a node first, then remove it
    apply_patch(flow, [{"op": "addNode", "node": {"id": "temp-node", "type": "log.message"}}])
    assert any(n.id == "temp-node" for n in flow.nodes)
    apply_patch(flow, [{"op": "removeNode", "nodeId": "temp-node"}])
    assert not any(n.id == "temp-node" for n in flow.nodes)


def test_remove_node_removes_edges(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    # Add a node + edge, then remove the node
    apply_patch(
        flow,
        [
            {"op": "addNode", "node": {"id": "temp-node", "type": "log.message"}},
            {"op": "addEdge", "from": "transform", "to": "temp-node"},
        ],
    )
    assert any(e.from_ == "transform" and e.to == "temp-node" for e in flow.edges)
    apply_patch(flow, [{"op": "removeNode", "nodeId": "temp-node"}])
    assert not any(e.to == "temp-node" for e in flow.edges)


def test_remove_entrypoint_rejected(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    with pytest.raises(PatchError, match="entrypoint"):
        apply_patch(flow, [{"op": "removeNode", "nodeId": "sender-http"}])


def test_remove_last_node_rejected(temp_project: Project) -> None:
    """A flow must have at least one node."""
    flow = _get_flow(temp_project)
    # Remove all nodes one by one — the last one should fail
    node_ids = [n.id for n in flow.nodes]
    for nid in node_ids[:-1]:
        apply_patch(flow, [{"op": "removeNode", "nodeId": nid}])
    with pytest.raises(PatchError, match="last node"):
        apply_patch(flow, [{"op": "removeNode", "nodeId": node_ids[-1]}])


# ---------------------------------------------------------------------
# updateNodeConfig
# ---------------------------------------------------------------------


def test_update_node_config_merge(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    # Find the content modifier in the error subprocess
    # Actually, let's update the receiver's timeout
    node = next(n for n in flow.nodes if n.id == "receiver-s4-eu")
    apply_patch(
        flow, [{"op": "updateNodeConfig", "nodeId": "receiver-s4-eu", "config": {"timeoutSeconds": 60}}]
    )
    assert node.config["timeoutSeconds"] == 60
    # Other keys should be preserved (merge mode)
    assert "url" in node.config
    assert "method" in node.config


def test_update_node_config_not_found(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    with pytest.raises(PatchError, match="not found"):
        apply_patch(flow, [{"op": "updateNodeConfig", "nodeId": "nonexistent", "config": {"x": 1}}])


# ---------------------------------------------------------------------
# addEdge / removeEdge
# ---------------------------------------------------------------------


def test_add_edge(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    apply_patch(
        flow,
        [
            {"op": "addNode", "node": {"id": "new-node", "type": "log.message"}},
            {"op": "addEdge", "from": "transform", "to": "new-node"},
        ],
    )
    assert any(e.from_ == "transform" and e.to == "new-node" for e in flow.edges)


def test_add_edge_duplicate_rejected(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    existing_edge = flow.edges[0]
    with pytest.raises(PatchError, match="already exists"):
        apply_patch(flow, [{"op": "addEdge", "from": existing_edge.from_, "to": existing_edge.to}])


def test_add_edge_dangling_rejected(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    with pytest.raises(PatchError, match="not found"):
        apply_patch(flow, [{"op": "addEdge", "from": "nonexistent", "to": "transform"}])


def test_remove_edge(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    original_count = len(flow.edges)
    edge_to_remove = flow.edges[0]
    apply_patch(flow, [{"op": "removeEdge", "from": edge_to_remove.from_, "to": edge_to_remove.to}])
    assert len(flow.edges) == original_count - 1


def test_remove_edge_not_found(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    with pytest.raises(PatchError, match="not found"):
        apply_patch(flow, [{"op": "removeEdge", "from": "nonexistent", "to": "also-nonexistent"}])


# ---------------------------------------------------------------------
# moveNode
# ---------------------------------------------------------------------


def test_move_node(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    assert flow.diagram is not None
    apply_patch(flow, [{"op": "moveNode", "nodeId": "transform", "position": {"x": 999, "y": 888}}])
    dn = next(n for n in flow.diagram["nodes"] if n["id"] == "transform")
    assert dn["position"] == {"x": 999, "y": 888}


def test_move_node_creates_diagram_entry(temp_project: Project) -> None:
    """If a node has no diagram entry, moveNode should create one."""
    flow = _get_flow(temp_project)
    # Add a node without a position
    apply_patch(flow, [{"op": "addNode", "node": {"id": "positionless", "type": "log.message"}}])
    # Now move it
    apply_patch(flow, [{"op": "moveNode", "nodeId": "positionless", "position": {"x": 50, "y": 60}}])
    dn = next(n for n in flow.diagram["nodes"] if n["id"] == "positionless")
    assert dn["position"] == {"x": 50, "y": 60}


# ---------------------------------------------------------------------
# Base revision validation
# ---------------------------------------------------------------------


def test_base_revision_mismatch(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    with pytest.raises(PatchError, match="revision mismatch"):
        apply_patch(
            flow,
            [{"op": "addNode", "node": {"id": "x", "type": "log.message"}}],
            base_revision="abc1234",
            current_revision="def5678",
        )


def test_base_revision_match_ok(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    apply_patch(
        flow,
        [{"op": "addNode", "node": {"id": "x", "type": "log.message"}}],
        base_revision="abc1234",
        current_revision="abc1234",
    )
    assert any(n.id == "x" for n in flow.nodes)


# ---------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------


def test_patch_rejects_cycle(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    # Add an edge that creates a cycle: transform -> route-by-region -> transform
    with pytest.raises(PatchError, match="cycle|validation failed"):
        apply_patch(flow, [{"op": "addEdge", "from": "route-by-region", "to": "transform"}])


# ---------------------------------------------------------------------
# write_flow
# ---------------------------------------------------------------------


def test_write_flow_persists_changes(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    apply_patch(flow, [{"op": "addNode", "node": {"id": "persisted-node", "type": "log.message"}}])
    write_flow(flow)

    # Reload the project and verify the node is on disk
    reloaded = Project.load(temp_project.root)
    reloaded_flow = reloaded.get_flow("order-to-s4")
    assert any(n.id == "persisted-node" for n in reloaded_flow.nodes)


def test_write_flow_canonical_ordering(temp_project: Project) -> None:
    """Written flow.yaml should have nodes sorted by ID and edges by (from, to)."""
    flow = _get_flow(temp_project)
    write_flow(flow)
    flow_yaml = flow.source_path.read_text(encoding="utf-8")
    data = yaml.safe_load(flow_yaml)
    node_ids = [n["id"] for n in data["spec"]["nodes"]]
    assert node_ids == sorted(node_ids), f"nodes not sorted: {node_ids}"
    edge_keys = [(e["from"], e["to"]) for e in data["spec"]["edges"]]
    assert edge_keys == sorted(edge_keys), f"edges not sorted: {edge_keys}"


# ---------------------------------------------------------------------
# Unknown operation
# ---------------------------------------------------------------------


def test_unknown_operation_rejected(temp_project: Project) -> None:
    flow = _get_flow(temp_project)
    with pytest.raises(PatchError, match="unknown patch operation"):
        apply_patch(flow, [{"op": "doSomethingWeird"}])
