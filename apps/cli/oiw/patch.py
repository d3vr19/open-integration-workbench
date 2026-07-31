"""Typed patch operations on integration flow IR.

Spec ref: §12.5 (Typed Patch Format), §12.1 (LLM never edits files directly;
all mutations go through typed patch operations).

This module implements the patch operations the UI and future LLM tools use
to mutate a flow. Every operation is validated before application.

Supported operations:
  - addNode          — add a new node with optional diagram position
  - removeNode       — remove a node (and its edges) by ID
  - updateNodeConfig — replace a node's config (partial merge)
  - addEdge          — add an edge
  - removeEdge       — remove an edge by from+to (optionally by condition)
  - moveNode         — update a node's position in diagram.json

Each patch carries a `baseRevision` (git HEAD sha) so the server can reject
stale writes (spec §12.5: "The server validates: base revision matches HEAD").
"""

from __future__ import annotations

import dataclasses
from typing import Any

import yaml

from .project import FlowEdge, FlowNode, IntegrationFlow


class PatchError(Exception):
    """Raised when a patch operation is invalid."""


@dataclasses.dataclass
class PatchResult:
    """Result of applying a patch."""

    flow: IntegrationFlow
    operations_applied: int
    new_revision: str | None = None
    semantic_diff: str = ""


def apply_patch(
    flow: IntegrationFlow,
    operations: list[dict[str, Any]],
    base_revision: str | None = None,
    current_revision: str | None = None,
) -> PatchResult:
    """Apply a list of typed patch operations to a flow.

    Spec §12.5: validates base revision, all referenced nodes exist, schema
    validates, no cycles introduced. Returns the updated flow.

    Args:
        flow: The flow to patch (mutated in place).
        operations: List of patch operation dicts.
        base_revision: The revision the client based its patch on.
        current_revision: The server's current HEAD revision.

    Returns:
        PatchResult with the updated flow and count of applied operations.
    """
    if base_revision and current_revision and base_revision != current_revision:
        raise PatchError(f"base revision mismatch: client={base_revision}, server={current_revision}")

    applied = 0
    for op in operations:
        kind = op.get("op") or op.get("operation")
        if kind == "addNode":
            _op_add_node(flow, op)
        elif kind == "removeNode":
            _op_remove_node(flow, op)
        elif kind == "updateNodeConfig":
            _op_update_node_config(flow, op)
        elif kind == "addEdge":
            _op_add_edge(flow, op)
        elif kind == "removeEdge":
            _op_remove_edge(flow, op)
        elif kind == "moveNode":
            _op_move_node(flow, op)
        else:
            raise PatchError(f"unknown patch operation: {kind!r}")
        applied += 1

    # Post-patch validation: no cycles, no dangling edges
    _validate_graph(flow)

    return PatchResult(flow=flow, operations_applied=applied, new_revision=current_revision)


def write_flow(flow: IntegrationFlow) -> None:
    """Write the flow IR + diagram back to disk.

    Spec §7.3 rule 4: layout separation — flow.yaml holds semantics,
    diagram.json holds x/y coordinates.
    Spec §7.3 rule 7: canonical ordering — nodes sorted by ID, edges
    sorted by (from, to) for deterministic diffs.
    """
    if flow.source_path is None:
        raise PatchError("flow has no source_path; cannot write back")
    flow_dir = flow.source_path.parent

    # Write flow.yaml (canonical ordering)
    flow_data = _flow_to_dict(flow)
    flow_yaml = yaml.safe_dump(flow_data, sort_keys=True, default_flow_style=False, allow_unicode=True)
    flow.source_path.write_text(flow_yaml, encoding="utf-8")

    # Write diagram.json if we have diagram data
    if flow.diagram is not None:
        import json

        diagram_path = flow_dir / "diagram.json"
        diagram_path.write_text(
            json.dumps(flow.diagram, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _flow_to_dict(flow: IntegrationFlow) -> dict[str, Any]:
    """Serialize a flow back to its YAML dict form (canonical ordering)."""
    nodes = sorted(flow.nodes, key=lambda n: n.id)
    edges = sorted(flow.edges, key=lambda e: (e.from_, e.to))

    spec: dict[str, Any] = {
        "entrypoints": [
            {
                "id": e.id,
                "type": e.type,
                "config": e.config,
                "fidelity": e.fidelity,
            }
            for e in flow.entrypoints
        ],
        "nodes": [
            {
                "id": n.id,
                "type": n.type,
                "config": n.config,
                "fidelity": n.fidelity,
            }
            for n in nodes
        ],
        "edges": [
            {
                "from": e.from_,
                "to": e.to,
                **({"condition": e.condition} if e.condition else {}),
            }
            for e in edges
        ],
        "extensions": flow.extensions or {},
    }
    if flow.error_handling:
        spec["errorHandling"] = {
            "defaultExceptionSubprocess": {
                "steps": [
                    {
                        "id": s.id,
                        "type": s.type,
                        "config": s.config,
                        "fidelity": s.fidelity,
                    }
                    for s in flow.error_handling.steps
                ]
            }
        }

    meta: dict[str, Any] = {
        "id": flow.id,
        "name": flow.name,
        "version": flow.version,
        "labels": flow.labels or {},
    }
    if flow.generated_by:
        meta["generatedBy"] = flow.generated_by

    return {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationFlow",
        "metadata": meta,
        "spec": spec,
    }


# ---------------------------------------------------------------------
# Individual operations
# ---------------------------------------------------------------------


def _op_add_node(flow: IntegrationFlow, op: dict[str, Any]) -> None:
    """Add a new node to the flow."""
    node_data = op.get("node")
    if not node_data:
        raise PatchError("addNode: missing 'node'")
    node_id = node_data.get("id")
    if not node_id:
        raise PatchError("addNode: node.id is required")
    # Check for duplicate
    existing_ids = {n.id for n in flow.nodes} | {e.id for e in flow.entrypoints}
    if node_id in existing_ids:
        raise PatchError(f"addNode: duplicate node id '{node_id}'")

    node = FlowNode(
        id=node_id,
        type=node_data.get("type", "log.message"),
        config=node_data.get("config", {}) or {},
        fidelity=node_data.get("fidelity", "simulated"),
    )
    flow.nodes.append(node)

    # Add diagram position if provided
    position = op.get("position")
    if position and flow.diagram is not None:
        flow.diagram.setdefault("nodes", []).append(
            {
                "id": node_id,
                "position": position,
            }
        )


def _op_remove_node(flow: IntegrationFlow, op: dict[str, Any]) -> None:
    """Remove a node and all its edges."""
    node_id = op.get("nodeId") or op.get("node")
    if not node_id:
        raise PatchError("removeNode: nodeId is required")
    # Don't allow removing entrypoints
    if any(e.id == node_id for e in flow.entrypoints):
        raise PatchError(f"removeNode: cannot remove entrypoint '{node_id}'")
    # Remove the node
    flow.nodes = [n for n in flow.nodes if n.id != node_id]
    if not flow.nodes:
        raise PatchError("removeNode: cannot remove the last node")
    # Remove edges referencing this node
    flow.edges = [e for e in flow.edges if e.from_ != node_id and e.to != node_id]
    # Remove from error handling steps
    if flow.error_handling:
        flow.error_handling.steps = [s for s in flow.error_handling.steps if s.id != node_id]
    # Remove from diagram
    if flow.diagram is not None:
        flow.diagram["nodes"] = [n for n in flow.diagram.get("nodes", []) if n.get("id") != node_id]
        flow.diagram["edges"] = [
            e for e in flow.diagram.get("edges", []) if e.get("from") != node_id and e.get("to") != node_id
        ]


def _op_update_node_config(flow: IntegrationFlow, op: dict[str, Any]) -> None:
    """Update a node's config (partial merge)."""
    node_id = op.get("nodeId") or op.get("node")
    if not node_id:
        raise PatchError("updateNodeConfig: nodeId is required")
    config_patch = op.get("config")
    if config_patch is None:
        raise PatchError("updateNodeConfig: config is required")

    node = _find_node(flow, node_id)
    if node is None:
        raise PatchError(f"updateNodeConfig: node '{node_id}' not found")

    # Partial merge: update provided keys, don't replace the whole config
    if op.get("merge", True):
        node.config.update(config_patch)
    else:
        node.config = config_patch


def _op_add_edge(flow: IntegrationFlow, op: dict[str, Any]) -> None:
    """Add an edge between two nodes."""
    from_id = op.get("from")
    to_id = op.get("to")
    if not from_id or not to_id:
        raise PatchError("addEdge: 'from' and 'to' are required")
    # Validate endpoints exist
    all_ids = {n.id for n in flow.nodes} | {e.id for e in flow.entrypoints}
    if from_id not in all_ids:
        raise PatchError(f"addEdge: 'from' node '{from_id}' not found")
    if to_id not in all_ids:
        raise PatchError(f"addEdge: 'to' node '{to_id}' not found")
    # Check for duplicate
    condition = op.get("condition")
    for e in flow.edges:
        if e.from_ == from_id and e.to == to_id and e.condition == condition:
            raise PatchError(f"addEdge: edge already exists ({from_id} → {to_id})")
    flow.edges.append(FlowEdge(from_=from_id, to=to_id, condition=condition))
    # Add to diagram
    if flow.diagram is not None:
        flow.diagram.setdefault("edges", []).append(
            {
                "from": from_id,
                "to": to_id,
                **({"condition": condition} if condition else {}),
            }
        )


def _op_remove_edge(flow: IntegrationFlow, op: dict[str, Any]) -> None:
    """Remove an edge by from+to (optionally by condition)."""
    from_id = op.get("from")
    to_id = op.get("to")
    if not from_id or not to_id:
        raise PatchError("removeEdge: 'from' and 'to' are required")
    condition = op.get("condition")
    original_count = len(flow.edges)
    flow.edges = [
        e
        for e in flow.edges
        if not (e.from_ == from_id and e.to == to_id and (condition is None or e.condition == condition))
    ]
    if len(flow.edges) == original_count:
        raise PatchError(f"removeEdge: edge not found ({from_id} → {to_id})")
    # Remove from diagram
    if flow.diagram is not None:
        flow.diagram["edges"] = [
            e
            for e in flow.diagram.get("edges", [])
            if not (
                e.get("from") == from_id
                and e.get("to") == to_id
                and (condition is None or e.get("condition") == condition)
            )
        ]


def _op_move_node(flow: IntegrationFlow, op: dict[str, Any]) -> None:
    """Update a node's position in diagram.json."""
    node_id = op.get("nodeId") or op.get("node")
    if not node_id:
        raise PatchError("moveNode: nodeId is required")
    position = op.get("position")
    if not position or "x" not in position or "y" not in position:
        raise PatchError("moveNode: position with x,y is required")
    if flow.diagram is None:
        flow.diagram = {"nodes": [], "edges": []}
    # Find or create the diagram node
    for dn in flow.diagram.get("nodes", []):
        if dn.get("id") == node_id:
            dn["position"] = {"x": position["x"], "y": position["y"]}
            return
    # Not found — add it
    flow.diagram.setdefault("nodes", []).append(
        {
            "id": node_id,
            "position": {"x": position["x"], "y": position["y"]},
        }
    )


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _find_node(flow: IntegrationFlow, node_id: str) -> FlowNode | None:
    """Find a node by ID (including entrypoints)."""
    for n in flow.nodes:
        if n.id == node_id:
            return n
    for e in flow.entrypoints:
        if e.id == node_id:
            return FlowNode(id=e.id, type=e.type, config=e.config, fidelity=e.fidelity)
    return None


def _validate_graph(flow: IntegrationFlow) -> None:
    """Post-patch validation: no cycles, no dangling edges, no duplicate IDs.

    Spec §12.5: "The server validates: base revision matches HEAD, all
    referenced nodes exist, schema validates, no cycles introduced."

    Note: we do NOT check reachability here — a user may add a node first
    and connect it with an edge in a subsequent operation. Reachability
    is checked by `oiw validate` (the full validation pipeline).
    """
    all_ids = {n.id for n in flow.nodes} | {e.id for e in flow.entrypoints}

    # Duplicate node IDs
    seen: set[str] = set()
    for n in flow.nodes:
        if n.id in seen:
            raise PatchError(f"post-patch validation failed: duplicate node id '{n.id}'")
        seen.add(n.id)

    # Dangling edges
    for e in flow.edges:
        if e.from_ not in all_ids:
            raise PatchError(f"post-patch validation failed: edge 'from' references unknown node '{e.from_}'")
        if e.to not in all_ids:
            raise PatchError(f"post-patch validation failed: edge 'to' references unknown node '{e.to}'")

    # Cycles (directed)
    from .validators.graph import _find_directed_cycle

    cycle = _find_directed_cycle([e.id for e in flow.entrypoints], flow.edges)
    if cycle:
        raise PatchError(f"post-patch validation failed: cycle detected: {' -> '.join(cycle)}")
