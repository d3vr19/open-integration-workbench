# `apps/mcp-server` — MCP protocol server (Phase 3)

> **Status: SUBSTANTIALLY COMPLETE.**
> Python implementation (ADR-PY-003). 12 MCP tools, 20 tests. JSON-RPC 2.0 over stdio.
> WP-04 Task 6: `flow.patch` tool now requires `baseRevision` (returns JSON-RPC -32602 on missing/stale).
> WP-05: `flow.create` tool added for creating new flows from scratch.

Exposes OIW's operations as MCP tools for external agents (Claude, Cursor, Windsurf).

## MCP tools (12)

| Tool | Description |
|------|-------------|
| `project.list` | List all projects in the workspace |
| `flow.get` | Get full flow IR (nodes, edges, diagram) |
| `flow.create` | Create a new integration flow with optional initial nodes/edges |
| `flow.patch` | Apply typed patch operations (§12.5) |
| `flow.validate` | Run schema + graph + rule validation |
| `flow.simulate` | Run local simulation, return trace + status |
| `resource.read` | Read a resource file (path traversal prevented) |
| `resource.write` | Create/update a resource file |
| `test.run` | Execute flow tests |
| `test.create` | Create a FlowTest YAML file |
| `build.export` | Compile IR to target-profile artifact |
| `git.status` | Get Git status + last build digest |

## Claude Desktop integration

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "oiw": {
      "command": "oiw-mcp",
      "env": { "OIW_WORKSPACE": "/path/to/projects" }
    }
  }
}
```

Spec ref: §5.1, §12.4 (MCP Tool Definitions), §21.3 (MCP Tools).
