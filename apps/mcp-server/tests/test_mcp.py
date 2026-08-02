"""Tests for the MCP server.

Spec ref: §12.4 (MCP Tool Definitions), §21.3 (MCP Tools).

Tests the JSON-RPC protocol handling and each tool's behaviour.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from oiw_mcp.main import handle_request
from oiw_mcp.tools import dispatch_tool, tool_definitions

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXAMPLES = REPO_ROOT / "examples"


@pytest.fixture(scope="module", autouse=True)
def _workspace_env():
    old = os.environ.get("OIW_WORKSPACE")
    os.environ["OIW_WORKSPACE"] = str(EXAMPLES)
    yield
    if old is not None:
        os.environ["OIW_WORKSPACE"] = old
    else:
        os.environ.pop("OIW_WORKSPACE", None)


# ---------------------------------------------------------------------
# Protocol tests
# ---------------------------------------------------------------------


def test_initialize() -> None:
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    resp = handle_request(req)
    assert resp is not None
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    result = resp["result"]
    assert "protocolVersion" in result
    assert "capabilities" in result
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "oiw-mcp-server"


def test_initialized_notification_returns_none() -> None:
    req = {"jsonrpc": "2.0", "method": "initialized", "params": {}}
    resp = handle_request(req)
    assert resp is None  # notifications don't get responses


def test_tools_list() -> None:
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    resp = handle_request(req)
    assert resp is not None
    tools = resp["result"]["tools"]
    assert len(tools) >= 10
    tool_names = [t["name"] for t in tools]
    # Spec §12.4 required tools
    assert "project.list" in tool_names
    assert "flow.get" in tool_names
    assert "flow.patch" in tool_names
    assert "flow.validate" in tool_names
    assert "flow.simulate" in tool_names
    assert "resource.write" in tool_names
    assert "test.run" in tool_names
    assert "build.export" in tool_names


def test_unknown_method_returns_error() -> None:
    req = {"jsonrpc": "2.0", "id": 3, "method": "nonexistent/method", "params": {}}
    resp = handle_request(req)
    assert resp is not None
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_tools_call_returns_text_content() -> None:
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "project.list", "arguments": {}},
    }
    resp = handle_request(req)
    assert resp is not None
    content = resp["result"]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "text"
    data = json.loads(content[0]["text"])
    assert "projects" in data
    assert len(data["projects"]) >= 2  # order-to-s4 + sftp-order-drop


# ---------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------


def test_all_tools_have_name_description_and_schema() -> None:
    for tool in tool_definitions():
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


def test_all_handlers_registered() -> None:
    """Every tool definition must have a corresponding handler."""
    from oiw_mcp.tools import _HANDLERS

    for tool in tool_definitions():
        assert tool["name"] in _HANDLERS, f"no handler for tool '{tool['name']}'"


# ---------------------------------------------------------------------
# Individual tool tests
# ---------------------------------------------------------------------


def test_project_list() -> None:
    result = dispatch_tool("project.list", {})
    data = json.loads(result)
    ids = [p["id"] for p in data["projects"]]
    assert "order-to-s4" in ids
    assert "sftp-order-drop" in ids


def test_flow_get() -> None:
    result = dispatch_tool("flow.get", {"projectId": "order-to-s4", "flowId": "order-to-s4"})
    data = json.loads(result)
    assert data["metadata"]["id"] == "order-to-s4"
    assert len(data["spec"]["nodes"]) > 0
    assert len(data["spec"]["edges"]) > 0


def test_flow_validate() -> None:
    result = dispatch_tool("flow.validate", {"projectId": "order-to-s4", "strict": True})
    data = json.loads(result)
    assert data["passed"] is True
    assert data["errorCount"] == 0


def test_flow_simulate() -> None:
    result = dispatch_tool(
        "flow.simulate",
        {
            "projectId": "order-to-s4",
            "flowId": "order-to-s4",
            "bodyInline": '{"orderId":"ORD-001","customerId":"CUST-42","region":"EU","items":[{"sku":"SKU-A","quantity":2}]}',
            "headers": {"Content-Type": "application/json"},
            "mocks": [{"target": "receiver-s4-eu", "respond": {"status": 201, "body": '{"id":"4711"}'}}],
        },
    )
    data = json.loads(result)
    assert data["status"] == "COMPLETED"
    assert len(data["trace"]) > 0


def test_resource_read() -> None:
    result = dispatch_tool(
        "resource.read",
        {
            "projectId": "order-to-s4",
            "path": "flows/order-to-s4/resources/scripts/normalizeOrder.groovy",
        },
    )
    data = json.loads(result)
    assert "content" in data
    assert "JsonSlurper" in data["content"]


def test_resource_read_path_traversal_rejected() -> None:
    result = dispatch_tool(
        "resource.read",
        {
            "projectId": "order-to-s4",
            "path": "../../../etc/passwd",
        },
    )
    data = json.loads(result)
    assert "error" in data


def test_test_run() -> None:
    result = dispatch_tool("test.run", {"projectId": "order-to-s4"})
    data = json.loads(result)
    assert data["total"] >= 2
    assert data["passed"] == data["total"]


def test_build_export() -> None:
    result = dispatch_tool(
        "build.export",
        {
            "projectId": "order-to-s4",
            "targetProfile": "sap-cloud-integration-2026-07",
        },
    )
    data = json.loads(result)
    assert data["digest"].startswith("sha256:")
    assert data["targetProfile"] == "sap-cloud-integration-2026-07"


def test_git_status() -> None:
    result = dispatch_tool("git.status", {"projectId": "order-to-s4"})
    data = json.loads(result)
    assert "branch" in data
    assert "headSha" in data
    assert "dirty" in data


def test_unknown_tool_returns_error() -> None:
    result = dispatch_tool("nonexistent.tool", {})
    assert "Error" in result


# ---------------------------------------------------------------------
# flow.patch (typed patches)
# ---------------------------------------------------------------------


def test_flow_patch_adds_node(tmp_path: Path) -> None:
    """Test flow.patch by copying the example to a temp dir and patching it.

    WP-04 Task 6: baseRevision is now required — we init a git repo in
    the temp dir so the handler can read a real HEAD sha.
    """
    import shutil
    import subprocess

    dest = tmp_path / "order-to-s4"
    shutil.copytree(EXAMPLES / "order-to-s4", dest)
    # Init git so _tool_flow_patch can read HEAD (WP-04 Task 6)
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
    head = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    old = os.environ.get("OIW_WORKSPACE")
    os.environ["OIW_WORKSPACE"] = str(tmp_path)
    try:
        result = dispatch_tool(
            "flow.patch",
            {
                "projectId": "order-to-s4",
                "flowId": "order-to-s4",
                "baseRevision": head,
                "operations": [
                    {
                        "op": "addNode",
                        "node": {
                            "id": "mcp-added",
                            "type": "log.message",
                            "config": {"level": "INFO", "message": "via MCP"},
                        },
                    },
                ],
            },
        )
        data = json.loads(result)
        assert data["applied"] == 1

        # Verify the node was written to disk
        result2 = dispatch_tool("flow.get", {"projectId": "order-to-s4", "flowId": "order-to-s4"})
        data2 = json.loads(result2)
        node_ids = [n["id"] for n in data2["spec"]["nodes"]]
        assert "mcp-added" in node_ids
    finally:
        if old is not None:
            os.environ["OIW_WORKSPACE"] = old
        else:
            os.environ.pop("OIW_WORKSPACE", None)


def test_flow_patch_missing_base_revision_rejected(tmp_path: Path) -> None:
    """WP-04 Task 6: flow.patch without baseRevision returns JSON-RPC -32602."""
    import shutil

    dest = tmp_path / "order-to-s4"
    shutil.copytree(EXAMPLES / "order-to-s4", dest)
    old = os.environ.get("OIW_WORKSPACE")
    os.environ["OIW_WORKSPACE"] = str(tmp_path)
    try:
        result = dispatch_tool(
            "flow.patch",
            {
                "projectId": "order-to-s4",
                "flowId": "order-to-s4",
                "operations": [
                    {"op": "addNode", "node": {"id": "x", "type": "log.message"}},
                ],
            },
        )
        data = json.loads(result)
        assert data.get("code") == -32602
        assert data.get("applied") == 0
        assert "baseRevision" in data.get("error", "")
    finally:
        if old is not None:
            os.environ["OIW_WORKSPACE"] = old
        else:
            os.environ.pop("OIW_WORKSPACE", None)


def test_flow_patch_stale_base_revision_conflict(tmp_path: Path) -> None:
    """WP-04 Task 6: stale baseRevision returns CONFLICT."""
    import shutil
    import subprocess

    dest = tmp_path / "order-to-s4"
    shutil.copytree(EXAMPLES / "order-to-s4", dest)
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(["git", "-C", str(dest), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(dest), "commit", "-q", "-m", "fixture"],
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
    try:
        result = dispatch_tool(
            "flow.patch",
            {
                "projectId": "order-to-s4",
                "flowId": "order-to-s4",
                "baseRevision": "stalesha1",
                "operations": [
                    {"op": "addNode", "node": {"id": "x", "type": "log.message"}},
                ],
            },
        )
        data = json.loads(result)
        assert data.get("code") == -32602
        assert data.get("status") == "CONFLICT"
        assert data.get("clientRevision") == "stalesha1"
    finally:
        if old is not None:
            os.environ["OIW_WORKSPACE"] = old
        else:
            os.environ.pop("OIW_WORKSPACE", None)
