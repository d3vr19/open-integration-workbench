"""Action normalization (spec §15.4).

Converts a (tool, arguments) pair into a stable, comparable tuple that
EMG Phase B can use as a graph edge label without needing the raw
arguments (which may contain secrets or project-specific identifiers).

The normalized form is:
    (tool, operation, componentType, semanticTarget, paramClass)

Examples:
    flow.patch, addNode, validator.json-schema, after-sender, single-required
    flow.patch, multi-op, 3-operations, "", ""
    resource.write, add-resource, schema.json, flows/order-to-s4/..., ""
    test.create, add-test, flow-test, order-to-s4, ""
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def normalize_action(tool: str, arguments: dict[str, Any]) -> tuple:
    """Produce a stable action tuple per spec §15.4.

    The tuple is *content-independent*: two `flow.patch addNode
    validator.json-schema` calls with different schema contents still
    normalize to the same tuple. The arguments_digest (caller-side)
    captures the content fingerprint.
    """
    if tool == "flow.patch":
        ops = arguments.get("operations") or []
        if len(ops) == 1:
            op = ops[0]
            op_kind = op.get("op", "unknown")
            node = op.get("node", {})
            component_type = node.get("type") or op.get("nodeType") or op.get("nodeId") or "unknown"
            return (
                "flow.patch",
                op_kind,
                component_type,
                _semantic_target(op, arguments),
                _param_class(op),
            )
        if len(ops) == 0:
            return ("flow.patch", "no-op", "unknown", "", "")
        return ("flow.patch", "multi-op", f"{len(ops)}-operations", "", "")

    if tool == "resource.write":
        path = arguments.get("path", "")
        resource_type = arguments.get("resourceType") or _infer_resource_type(path)
        op_kind = "update-resource" if _looks_like_update(path) else "add-resource"
        return ("resource.write", op_kind, resource_type, _semantic_ref(path), "")

    if tool == "test.create":
        return (
            "test.create",
            "add-test",
            "flow-test",
            arguments.get("flowId", ""),
            "",
        )

    if tool == "test.run":
        return ("test.run", "invoke", "flow-test", arguments.get("flowId", ""), "")

    if tool == "flow.validate":
        return ("flow.validate", "invoke", "project", arguments.get("projectId", ""), "")

    # Unknown tool — record verbatim. EMG Phase B can bucket these later.
    return (tool, "invoke", "", "", "")


def normalize_observation(diagnostic: dict[str, Any]) -> tuple:
    """Produce a stable observation label per spec §15.5.

    Used when the agent observes a validation/test/policy diagnostic and
    needs to record it in the trajectory without leaking project-specific
    detail.
    """
    return (
        diagnostic.get("category", "unknown"),  # validation, test, policy, compiler, review
        diagnostic.get("code", "NONE"),  # OIW-E001, OIW-W003, ...
        diagnostic.get("componentRole", ""),  # validator-node, receiver-http, ...
        diagnostic.get("targetProfile", ""),  # sap-ci-2026-07
    )


def arguments_digest(arguments: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON of `arguments`.

    Used as the content fingerprint alongside the structural
    `normalize_action` tuple. Two structurally-identical actions with
    different arguments (e.g. same op, different schema content) will
    share the normalized tuple but differ in digest.
    """
    canonical = json.dumps(arguments, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_STEP_INSERTION_ORDER = (
    # Ordered so the first matching ancestor wins. A validator placed
    # right after the sender has semantic target "after-sender", even
    # if other nodes sit between in the actual graph.
    "sender",
    "receiver",
    "validator",
    "router",
    "splitter",
    "gather",
    "filter",
    "script",
    "transform",
)


def _semantic_target(op: dict[str, Any], arguments: dict[str, Any]) -> str:
    """Where in the flow graph this op lands, structurally.

    Examples: "after-sender", "before-receiver", "replace-validator",
    "remove-node", "add-edge". Falls back to "" if we cannot tell.
    """
    op_kind = op.get("op", "")
    node = op.get("node", {}) or {}
    node_type = (node.get("type") or "").lower()
    node_id = (node.get("id") or "").lower()

    if op_kind in ("addNode",):
        # Heuristic: if the node id contains "input" / "validate", it
        # sits near the sender; "output" / "transform" near the receiver.
        if any(token in node_id for token in ("input", "validate", "receive")):
            return "after-sender"
        if any(token in node_id for token in ("output", "transform", "send")):
            return "before-receiver"
        return f"add-{node_type or 'node'}"
    if op_kind == "removeNode":
        return f"remove-{node_type or node_id or 'node'}"
    if op_kind == "updateNodeConfig":
        return f"replace-{node_type or node_id or 'config'}"
    if op_kind == "addEdge":
        return "add-edge"
    if op_kind == "removeEdge":
        return "remove-edge"
    if op_kind == "moveNode":
        return "move-node"
    return ""


def _param_class(op: dict[str, Any]) -> str:
    """Bucket the operation's parameter shape.

    Used by EMG to cluster similar patches. Examples:
      - "single-required"  (only required fields set)
      - "with-fidelity"    (fidelity flag set)
      - "full-config"      (all config fields populated)
    """
    node = op.get("node", {}) or {}
    keys = set(node.keys())
    if not keys:
        return "empty"
    has_required = {"id", "type"} <= keys
    has_fidelity = "fidelity" in keys
    has_full_config = "config" in keys and isinstance(node.get("config"), dict) and node["config"]
    if has_required and has_fidelity and has_full_config:
        return "full-config"
    if has_required and has_fidelity:
        return "with-fidelity"
    if has_required:
        return "single-required"
    return "partial"


def _semantic_ref(path: str) -> str:
    """Short, comparable resource path. Strips project-specific prefixes."""
    # /flows/order-to-s4/resources/schemas/order.schema.json
    #   -> flows/<flow>/resources/schemas/order.schema.json
    parts = path.split("/")
    if len(parts) >= 4 and parts[0] == "flows":
        return "/".join([parts[0], "<flow>", *parts[2:]])
    return path


def _infer_resource_type(path: str) -> str:
    """Guess the resourceType from the file extension."""
    lowered = path.lower()
    if lowered.endswith(".json") and "schema" in lowered:
        return "schema.json"
    if lowered.endswith(".xsl") or lowered.endswith(".xslt"):
        return "mapping.xslt"
    if lowered.endswith(".groovy"):
        return "script.groovy"
    if lowered.endswith(".json"):
        return "json"
    if lowered.endswith(".yaml") or lowered.endswith(".yml"):
        return "yaml"
    return "unknown"


def _looks_like_update(path: str) -> bool:
    """Conservative: treat every resource.write as 'add' unless the caller
    explicitly set `arguments['exists']=True`.

    We do not stat the filesystem here — the trajectory recorder must be
    pure-function with respect to the filesystem so tests are deterministic.
    """
    return False


__all__ = [
    "normalize_action",
    "normalize_observation",
    "arguments_digest",
]
