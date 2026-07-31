# OIW MCP Server (`apps/mcp-server`)

> **Phase 3 — LLM-Assisted Engineering (spec §12, §19 Phase 3).**

The MCP (Model Context Protocol) server exposes OIW's operations as MCP tools
that external agents (Claude, Cursor, Windsurf, etc.) can call. Spec §12.4
defines the tool surface; §21.3 lists additional EMG-related tools.

## Architecture

The MCP server is a thin protocol adapter — it speaks JSON-RPC 2.0 over stdio
(the standard MCP transport for local servers) and delegates all business logic
to the existing `oiw` CLI package. No duplication.

```
External agent (Claude, Cursor, etc.)
        │  JSON-RPC 2.0 over stdio
        ▼
┌─────────────────────┐
│   oiw-mcp-server    │  ← this package
│   (apps/mcp-server) │
└─────────┬───────────┘
          │  direct function calls
          ▼
┌─────────────────────┐
│   oiw CLI package   │  ← apps/cli/oiw/
│   (project, patch,  │
│    runtime, testing)│
└─────────────────────┘
```

## Run

```bash
# Install
pip install -e apps/mcp-server

# Run as a stdio server (for Claude Desktop, Cursor, etc.)
oiw-mcp

# Or with a custom workspace
OIW_WORKSPACE=/path/to/projects oiw-mcp
```

## MCP tools exposed (spec §12.4)

| Tool | Description |
|------|-------------|
| `project.list` | List all integration projects in the workspace |
| `flow.get` | Get the full IR of an integration flow |
| `flow.patch` | Apply typed patch operations to a flow (§12.5) |
| `flow.validate` | Run full validation on a flow |
| `flow.simulate` | Run local simulation with a test case |
| `resource.write` | Create or update a resource file |
| `resource.read` | Read a resource file |
| `test.run` | Execute tests for a flow |
| `build.export` | Compile IR to target-profile artifact package |
| `git.status` | Get Git status + last build digest |

## MCP protocol

The server implements the MCP protocol over stdio:
- `initialize` — handshake with capabilities
- `tools/list` — returns the tool catalogue
- `tools/call` — executes a tool by name with arguments

All responses use JSON-RPC 2.0 format. Tool results are returned as text
content blocks.

## Security (spec §12.1, §16.3)

- The LLM **never** edits files directly — all mutations go through typed patch
  operations (`flow.patch`) or the resource write API (`resource.write`).
- The LLM **never** receives secret values — only `credentialRef` identifiers.
- The LLM **never** deploys — `build.export` produces an artifact, but
  deployment requires Phase 4's approval-gated state machine.
- All repository text is treated as untrusted data (prompt injection defense).
- Tool permissions are enforced server-side, not by prompt instruction alone.

## Configuring with Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "oiw": {
      "command": "oiw-mcp",
      "env": {
        "OIW_WORKSPACE": "/path/to/your/projects"
      }
    }
  }
}
```
