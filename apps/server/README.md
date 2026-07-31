# `apps/server` — Kotlin/Spring Boot modular monolith (Phase 2)

> **Status: NOT YET IMPLEMENTED.**
> See `DEVELOPMENT_LOG.md` → Open Work item OW-002.

When implemented, this will be the modular monolith providing:

- REST API (spec §21.1)
- WebSocket endpoints (spec §21.2)
- Auth + RBAC (spec §16.2)
- Project & Git service
- AI orchestrator (Phase 3+)
- Validation engine
- Compatibility compiler interface

The current Python CLI (`apps/cli`) is the reference implementation for the
project loader, validator, compiler, and runtime; the Kotlin server will use
the same JSON Schemas and test fixtures.

Spec ref: §5.1, §6.2 (Backend stack).
