# ADR-PY-003: Python MCP server prototype

- Status: DEVIATION — TEMPORARY
- Date: 2026-07-31
- Spec ref: §5.1 (mandates Kotlin MCP server), §12.4 (MCP Tool Definitions), §21.3 (MCP Tools)
- Decider: Implementing agent (Phase 3 starter)

## Context

Spec §5.1 mandates a Kotlin MCP server at `apps/mcp-server`. The MCP protocol
(JSON-RPC 2.0 over stdio) is language-agnostic. The existing `oiw` CLI package
already implements all the business logic the MCP tools need (project loading,
flow patching, validation, simulation, resource I/O, tests, builds, git status).

## Decision

Implement the MCP server in Python at `apps/mcp-server/` as a thin protocol
adapter that delegates to the existing `oiw` CLI package. The server:

- Speaks JSON-RPC 2.0 over stdio (the standard MCP transport).
- Exposes all §12.4 tools by calling `oiw` functions directly — no subprocess, no duplication.
- Returns tool results as text content blocks (MCP standard).

The MCP tool catalogue (§12.4) is implementation-language-agnostic. When the
Kotlin migration (OW-001, OW-002) lands, the MCP server can be re-implemented
in Kotlin against the same tool definitions — or the Python server can remain
as the reference implementation, since it imports the same `oiw` logic.

## Consequences

- Positive: External agents (Claude, Cursor, Windsurf) can connect to OIW immediately.
- Positive: All 10 §12.4 tools are implemented and tested (18 tests).
- Positive: The MCP server inherits the CLI's security model — typed patches only, path traversal prevention, no secret exposure.
- Negative: Three Python implementations exist during the migration window (CLI, server, MCP server). All three import the same `oiw` package — no duplication.
- Neutral: Migration to Kotlin is a mechanical translation against the same MCP protocol. The 18 MCP tests survive unchanged (they test the protocol, not the implementation).

## Alternatives considered

- **Build the Kotlin MCP server from day one.** Rejected: would block Phase 3
  until the Kotlin CLI migration (OW-001) is complete. The Python prototype
  unblocks LLM-assisted engineering immediately.
- **Have the MCP server call the REST API via HTTP.** Rejected: adds a network
  hop and a dependency on the FastAPI server running. The MCP server imports
  `oiw` directly — it works standalone with just the CLI installed.
- **Use the official MCP Python SDK.** Considered but rejected for now — the
  protocol is simple enough (JSON-RPC over stdio) that a 100-line implementation
  suffices. The SDK can be adopted later if we need features like SSE transport
  or resource subscriptions.

## Migration plan

The Kotlin MCP server (when implemented) will:
1. Implement the same JSON-RPC 2.0 over stdio protocol.
2. Expose the same 10 §12.4 tools with the same input schemas.
3. Pass the same 18 MCP tests (translated to Kotlin).
4. Replace `apps/mcp-server/` in Docker Compose.

The Python prototype is deleted once the Kotlin server passes CI.
