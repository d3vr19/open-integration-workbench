"""MCP server — JSON-RPC 2.0 over stdio.

Spec ref: §12.4 (MCP Tool Definitions), §21.3 (MCP Tools), §18 (MCP protocol).
ADR-PY-003: Python prototype of the spec's Kotlin MCP server.

The server reads JSON-RPC 2.0 messages from stdin (one per line) and writes
responses to stdout. This is the standard stdio transport for MCP servers.

Protocol:
  Client → Server: {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
  Server → Client: {"jsonrpc": "2.0", "id": 1, "result": {...}}

  Client → Server: {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
  Server → Client: {"jsonrpc": "2.0", "id": 2, "result": {"tools": [...]}}

  Client → Server: {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "project.list", "arguments": {}}}
  Server → Client: {"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": "..."}]}}
"""

from __future__ import annotations

import json
import sys
from typing import Any

from . import __version__
from .tools import dispatch_tool, tool_definitions


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """Handle a single JSON-RPC request. Returns the response dict, or None for notifications."""
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": "oiw-mcp-server",
                    "version": __version__,
                },
            },
        }

    if method == "initialized":
        # Notification — no response
        return None

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": tool_definitions()},
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        result_text = dispatch_tool(tool_name, tool_args)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": result_text}],
            },
        }

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"method not found: {method}",
        },
    }


def serve() -> None:
    """Main stdio loop. Reads lines from stdin, writes responses to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "parse error"},
            }
            print(json.dumps(response), flush=True)
            continue

        response = handle_request(request)
        if response is not None:
            print(json.dumps(response), flush=True)


def main() -> None:
    """Entry point for the oiw-mcp console script."""
    serve()


if __name__ == "__main__":
    main()
