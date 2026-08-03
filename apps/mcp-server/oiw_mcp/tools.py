"""MCP tool definitions.

Spec ref: §12.4 (MCP Tool Definitions).

Each tool is defined with its name, description, and input schema (JSON Schema).
The tool handler receives the arguments dict and returns a text result.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .config import workspace_root
from .workspace import load_project as _load_project

# Tool handler type: takes arguments dict, returns a string (text result)
ToolHandler = Callable[[dict[str, Any]], str]


# ---------------------------------------------------------------------
# Tool catalogue (spec §12.4)
# ---------------------------------------------------------------------


def tool_definitions() -> list[dict[str, Any]]:
    """Return the list of MCP tool definitions (for tools/list)."""
    return [
        {
            "name": "project.list",
            "description": "List all integration projects in the workspace.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "flow.get",
            "description": "Get the full IR of an integration flow, including nodes, edges, and diagram.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "flowId": {"type": "string"},
                },
                "required": ["projectId", "flowId"],
            },
        },
        {
            "name": "flow.patch",
            "description": (
                "Apply typed patch operations to an integration flow (spec §12.5). "
                "Operations: addNode, removeNode, updateNodeConfig, addEdge, removeEdge, moveNode. "
                "The LLM never edits files directly — all mutations go through this tool."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "flowId": {"type": "string"},
                    "operations": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of patch operations. Each must have an 'op' field.",
                    },
                    "baseRevision": {
                        "type": "string",
                        "description": (
                            "The git HEAD sha the patch is based on. REQUIRED (spec §12.5, WP-04 Task 6): "
                            "the server rejects stale writes with a 409-equivalent error. "
                            "The agent planner captures HEAD at planning time and injects it into every "
                            "flow.patch step (WP-04 Task 2)."
                        ),
                    },
                },
                "required": ["projectId", "flowId", "operations", "baseRevision"],
            },
        },
        {
            "name": "flow.create",
            "description": (
                "Create a new integration flow in a project (spec §9.4, WP-05 fix for bench-002). "
                "Creates the flow directory + flow.yaml skeleton + diagram.json. "
                "The agent uses this before flow.patch when creating a brand-new flow."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "flowId": {
                        "type": "string",
                        "description": "The flow ID (also the directory name under flows/).",
                    },
                    "name": {
                        "type": "string",
                        "description": "Human-readable flow name.",
                    },
                    "initialNodes": {
                        "type": "array",
                        "description": "Optional initial set of nodes to add.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "type": {"type": "string"},
                                "config": {"type": "object"},
                                "fidelity": {"type": "string"},
                            },
                        },
                    },
                    "initialEdges": {
                        "type": "array",
                        "description": "Optional initial edges between nodes.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string"},
                                "to": {"type": "string"},
                                "condition": {"type": "string"},
                            },
                        },
                    },
                },
                "required": ["projectId", "flowId", "name"],
            },
        },
        {
            "name": "flow.validate",
            "description": "Run full validation (schema + graph + rules) on a project. Returns diagnostics.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "strict": {
                        "type": "boolean",
                        "default": False,
                        "description": "Treat warnings as errors.",
                    },
                },
                "required": ["projectId"],
            },
        },
        {
            "name": "flow.simulate",
            "description": (
                "Run local simulation of a flow with given input. Returns the execution trace "
                "and final status (spec §9.2)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "flowId": {"type": "string"},
                    "bodyInline": {"type": "string", "description": "Inline input body."},
                    "bodyFile": {"type": "string", "description": "Path to a fixture file."},
                    "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                    "mocks": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                },
                "required": ["projectId", "flowId"],
            },
        },
        {
            "name": "resource.read",
            "description": "Read a resource file (Groovy, XSLT, JSON Schema, etc.). Path traversal is prevented.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "path": {
                        "type": "string",
                        "description": "Resource path (e.g. flows/x/resources/scripts/y.groovy).",
                    },
                },
                "required": ["projectId", "path"],
            },
        },
        {
            "name": "resource.write",
            "description": (
                "Create or update a resource file (spec §12.4). "
                "Only paths under flows/<flow>/resources/ are allowed."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["projectId", "path", "content"],
            },
        },
        {
            "name": "test.run",
            "description": "Execute tests for a flow. Returns pass/fail results.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "flowId": {
                        "type": "string",
                        "description": "Optional: run tests for a specific flow only.",
                    },
                },
                "required": ["projectId"],
            },
        },
        {
            "name": "test.create",
            "description": (
                "Create a test definition file for a flow (spec §12.4). "
                "Writes a FlowTest YAML file under flows/<flow>/tests/."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "flowId": {"type": "string"},
                    "testName": {
                        "type": "string",
                        "description": "Test name (file will be <testName>.yaml).",
                    },
                    "bodyInline": {"type": "string", "description": "Inline input body."},
                    "assertions": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of assertion dicts.",
                    },
                    "mocks": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                },
                "required": ["projectId", "flowId", "testName"],
            },
        },
        {
            "name": "build.export",
            "description": "Compile IR to a target-profile artifact package. Returns the build digest (spec §8, §4.7).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "targetProfile": {"type": "string", "description": "e.g. sap-cloud-integration-2026-07"},
                },
                "required": ["projectId", "targetProfile"],
            },
        },
        {
            "name": "git.status",
            "description": "Get Git status: branch, HEAD SHA, dirty flag, ahead count, last build digest.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                },
                "required": ["projectId"],
            },
        },
    ]


# ---------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------


def dispatch_tool(name: str, args: dict[str, Any]) -> str:
    """Execute a tool by name. Returns the result as a string."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Error: unknown tool '{name}'"
    try:
        return handler(args)
    except Exception as exc:
        return f"Error: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------


def _tool_project_list(args: dict[str, Any]) -> str:
    from oiw.project import Project, ProjectError

    root = workspace_root()
    if not root.is_dir():
        return json.dumps({"projects": [], "error": f"workspace not found: {root}"})

    projects = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "oiw.yaml").exists():
            try:
                project = Project.load(child)
                projects.append(
                    {
                        "id": child.name,
                        "name": project.name,
                        "flowCount": len(project.flows),
                        "testCount": len(project.tests),
                    }
                )
            except ProjectError:
                continue

    return json.dumps({"projects": projects}, indent=2)


def _tool_flow_get(args: dict[str, Any]) -> str:
    project = _load_project(args["projectId"])
    flow = project.get_flow(args["flowId"])

    nodes = [{"id": n.id, "type": n.type, "config": n.config, "fidelity": n.fidelity} for n in flow.nodes]
    edges = [
        {"from": e.from_, "to": e.to, **({"condition": e.condition} if e.condition else {})}
        for e in flow.edges
    ]
    return json.dumps(
        {
            "apiVersion": "oiw.dev/v1alpha1",
            "kind": "IntegrationFlow",
            "metadata": {"id": flow.id, "name": flow.name, "version": flow.version, "labels": flow.labels},
            "spec": {
                "entrypoints": [{"id": e.id, "type": e.type, "config": e.config} for e in flow.entrypoints],
                "nodes": nodes,
                "edges": edges,
            },
            "diagram": flow.diagram,
        },
        indent=2,
    )


def _tool_flow_create(args: dict[str, Any]) -> str:
    """Create a new flow in a project (WP-05 fix for bench-002).

    Creates the flow directory + flow.yaml skeleton + diagram.json.
    Optionally populates initial nodes + edges.
    """
    import yaml

    project = _load_project(args["projectId"])
    flow_id = args["flowId"]
    flow_name = args.get("name", flow_id)

    flow_dir = project.root / "flows" / flow_id
    if flow_dir.exists():
        return json.dumps(
            {"error": f"flow '{flow_id}' already exists", "flowId": flow_id},
            indent=2,
        )
    flow_dir.mkdir(parents=True)

    # Build initial flow YAML
    initial_nodes = args.get("initialNodes", [])
    initial_edges = args.get("initialEdges", [])

    flow_data = {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationFlow",
        "metadata": {"id": flow_id, "name": flow_name, "version": 1, "labels": {}},
        "spec": {
            "entrypoints": [],
            "nodes": [
                {
                    "id": n.get("id", f"node-{i}"),
                    "type": n.get("type", "log.message"),
                    "config": n.get("config", {}),
                    "fidelity": n.get("fidelity", "simulated"),
                }
                for i, n in enumerate(initial_nodes)
            ],
            "edges": [{"from": e.get("from", ""), "to": e.get("to", "")} for e in initial_edges],
            "extensions": {},
        },
    }

    flow_yaml = yaml.safe_dump(flow_data, sort_keys=True, default_flow_style=False, allow_unicode=True)
    (flow_dir / "flow.yaml").write_text(flow_yaml, encoding="utf-8")

    # Create empty tests dir
    (flow_dir / "tests").mkdir(exist_ok=True)

    # Create diagram.json
    import json as _json

    diagram = {
        "nodes": [
            {"id": n.get("id", f"node-{i}"), "position": {"x": 100 + i * 200, "y": 100}}
            for i, n in enumerate(initial_nodes)
        ],
        "edges": [{"from": e.get("from", ""), "to": e.get("to", "")} for e in initial_edges],
    }
    (flow_dir / "diagram.json").write_text(
        _json.dumps(diagram, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return json.dumps(
        {
            "created": True,
            "flowId": flow_id,
            "name": flow_name,
            "nodeCount": len(initial_nodes),
            "edgeCount": len(initial_edges),
        },
        indent=2,
    )


def _tool_flow_patch(args: dict[str, Any]) -> str:
    from oiw.patch import PatchError, apply_patch, write_flow

    project = _load_project(args["projectId"])
    flow = project.get_flow(args["flowId"])

    operations = args.get("operations", [])
    base_revision = args.get("baseRevision")

    # WP-04 Task 6: baseRevision is REQUIRED. Missing or stale revision
    # produces a JSON-RPC -32602 (Invalid params) / 409-equivalent error.
    if not base_revision:
        return json.dumps(
            {
                "error": "flow.patch requires 'baseRevision' (spec §12.5, WP-04 Task 6).",
                "code": -32602,
                "applied": 0,
            },
            indent=2,
        )

    # Get current HEAD for base-revision validation
    import subprocess

    try:
        result = subprocess.run(
            ["git", "-C", str(project.root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        current_revision = result.stdout.strip()
    except Exception:
        current_revision = "unknown"

    if base_revision != current_revision:
        return json.dumps(
            {
                "error": (
                    f"baseRevision conflict: client={base_revision}, server={current_revision}. "
                    "Re-fetch the flow and retry (spec §12.5, WP-04 Task 6)."
                ),
                "code": -32602,  # JSON-RPC Invalid params; surface maps to HTTP 409
                "status": "CONFLICT",
                "applied": 0,
                "clientRevision": base_revision,
                "serverRevision": current_revision,
            },
            indent=2,
        )

    try:
        result = apply_patch(
            flow=flow,
            operations=operations,
            base_revision=base_revision,
            current_revision=current_revision,
        )
        write_flow(flow)
    except PatchError as exc:
        return json.dumps({"error": str(exc), "applied": 0}, indent=2)

    return json.dumps(
        {
            "applied": result.operations_applied,
            "flowId": flow.id,
            "revision": current_revision,
        },
        indent=2,
    )


def _tool_flow_validate(args: dict[str, Any]) -> str:
    from oiw.schema_validator import validate_project
    from oiw.validators.graph import validate_flow_graph
    from oiw.validators.rules import run_rule_validators

    project = _load_project(args["projectId"])
    strict = args.get("strict", False)

    errors: list[str] = []
    warnings: list[str] = []

    schema_results = validate_project(project)
    errors.extend(schema_results.errors)
    warnings.extend(schema_results.warnings)

    for flow in project.flows:
        graph_errors, graph_warnings = validate_flow_graph(flow)
        errors.extend(graph_errors)
        warnings.extend(graph_warnings)

    rule_errors, rule_warnings = run_rule_validators(project)
    errors.extend(rule_errors)
    warnings.extend(rule_warnings)

    if strict:
        errors.extend(warnings)
        warnings = []

    return json.dumps(
        {
            "errors": errors,
            "warnings": warnings,
            "errorCount": len(errors),
            "warningCount": len(warnings),
            "passed": len(errors) == 0,
        },
        indent=2,
    )


def _tool_flow_simulate(args: dict[str, Any]) -> str:
    from oiw.runtime.engine import execute_flow

    project = _load_project(args["projectId"])
    flow = project.get_flow(args["flowId"])

    # Resolve body
    if "bodyFile" in args:
        body = (project.root / args["bodyFile"]).read_bytes()
    elif "bodyInline" in args:
        body = args["bodyInline"].encode("utf-8")
    else:
        body = b""

    headers = args.get("headers", {})
    mocks = {m["target"]: m for m in args.get("mocks", [])}

    ctx = execute_flow(
        flow=flow,
        input_body=body,
        input_headers=headers,
        resources=project.resources,
        mocks=mocks,
    )

    return json.dumps(
        {
            "status": ctx.exchange_status,
            "durationMs": ctx.properties.get("__duration_ms__", 0),
            "trace": [
                {"nodeId": t.node_id, "direction": t.direction, "summary": t.summary} for t in ctx.trace
            ],
            "outboundCalls": [
                {"target": c["target"], "method": c["method"], "url": c["url"]} for c in ctx.outbound_calls
            ],
        },
        indent=2,
    )


def _tool_resource_read(args: dict[str, Any]) -> str:
    project = _load_project(args["projectId"])
    path = args["path"]

    # Path traversal check
    if ".." in path.split("/"):
        return json.dumps({"error": "path traversal not allowed"})

    full_path = (project.root / path).resolve()
    try:
        full_path.relative_to(project.root.resolve())
    except ValueError:
        return json.dumps({"error": "path escapes project root"})

    if not full_path.is_file():
        return json.dumps({"error": f"resource not found: {path}"})

    content = full_path.read_text(encoding="utf-8", errors="replace")
    return json.dumps({"path": path, "content": content, "size": len(content)}, indent=2)


def _tool_resource_write(args: dict[str, Any]) -> str:
    project = _load_project(args["projectId"])
    path = args["path"]
    content = args["content"]

    # Path traversal check
    if ".." in path.split("/"):
        return json.dumps({"error": "path traversal not allowed"})

    full_path = (project.root / path).resolve()
    try:
        rel = full_path.relative_to(project.root.resolve())
    except ValueError:
        return json.dumps({"error": "path escapes project root"})

    # Only allow writing under flows/*/resources/
    parts = rel.parts
    if len(parts) < 3 or parts[0] != "flows" or parts[2] != "resources":
        return json.dumps({"error": "resource must be under flows/<flow>/resources/"})

    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")
    return json.dumps({"path": path, "size": len(content), "written": True}, indent=2)


def _tool_test_run(args: dict[str, Any]) -> str:
    from oiw.testing import run_tests

    project = _load_project(args["projectId"])
    flow_id = args.get("flowId")

    results = run_tests(project, flow_id=flow_id)
    return json.dumps(
        {
            "results": [
                {
                    "flowId": r.flow_id,
                    "testName": r.test_name,
                    "passed": r.passed,
                    "durationMs": r.duration_ms,
                    "failures": r.failures,
                }
                for r in results
            ],
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
        },
        indent=2,
    )


def _tool_test_create(args: dict[str, Any]) -> str:
    """Create a test definition file. Spec §12.4 (test.create)."""
    import yaml

    project = _load_project(args["projectId"])
    flow_id = args["flowId"]
    test_name = args["testName"]

    # Build the FlowTest IR
    test_data = {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "FlowTest",
        "metadata": {"name": test_name},
        "spec": {
            "flow": flow_id,
            "input": {
                "entrypoint": "sender-http",
                "bodyInline": args.get("bodyInline", "{}"),
                "headers": {"Content-Type": "application/json"},
            },
            "assertions": args.get("assertions", [{"type": "exchange.status", "equals": "COMPLETED"}]),
            "mocks": args.get("mocks", []),
        },
    }

    # Write to flows/<flow>/tests/<testName>.yaml
    test_path = project.root / "flows" / flow_id / "tests" / f"{test_name}.yaml"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(
        yaml.safe_dump(test_data, sort_keys=True, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    return json.dumps(
        {
            "created": True,
            "path": str(test_path.relative_to(project.root)),
            "testName": test_name,
            "flowId": flow_id,
        },
        indent=2,
    )


def _tool_build_export(args: dict[str, Any]) -> str:
    from oiw.compiler.export import BuildError, build_artifact

    project = _load_project(args["projectId"])
    target_profile = args["targetProfile"]

    try:
        result = build_artifact(project, target_profile, project.root / "dist")
    except BuildError as exc:
        return json.dumps({"error": str(exc)}, indent=2)

    return json.dumps(
        {
            "digest": result.digest,
            "compilerVersion": result.compiler_version,
            "targetProfile": result.target_profile,
            "entryCount": len(result.entries),
            "outDir": str(result.out_dir),
        },
        indent=2,
    )


def _tool_git_status(args: dict[str, Any]) -> str:
    from oiw.git_ops import git_status

    project = _load_project(args["projectId"])
    status = git_status(project.root)
    return json.dumps(
        {
            "branch": status.branch,
            "headSha": status.head_sha,
            "dirty": status.dirty,
            "ahead": status.ahead,
            "lastBuildDigest": status.last_build_digest,
            "lastBuildTarget": status.last_build_target,
        },
        indent=2,
    )


# ---------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------


_HANDLERS: dict[str, ToolHandler] = {
    "project.list": _tool_project_list,
    "flow.get": _tool_flow_get,
    "flow.create": _tool_flow_create,
    "flow.patch": _tool_flow_patch,
    "flow.validate": _tool_flow_validate,
    "flow.simulate": _tool_flow_simulate,
    "resource.read": _tool_resource_read,
    "resource.write": _tool_resource_write,
    "test.run": _tool_test_run,
    "test.create": _tool_test_create,
    "build.export": _tool_build_export,
    "git.status": _tool_git_status,
}
