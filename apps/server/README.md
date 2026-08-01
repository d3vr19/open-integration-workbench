# `apps/server` — Kotlin/Spring Boot modular monolith (Phase 2+)

> **Status: NOT YET IMPLEMENTED.**
> The FastAPI prototype at `apps/server-python-prototype/` is the active implementation (ADR-PY-002).
> This directory is the Kotlin/Spring Boot production target (OW-002).

When implemented, this will be the modular monolith providing:
- REST API (spec §21.1) — same OpenAPI contract as the FastAPI prototype
- WebSocket endpoints (spec §21.2)
- Auth + RBAC (spec §16.2)
- Project & Git service
- AI orchestrator
- Validation engine
- Compatibility compiler interface

The FastAPI prototype's 76 tests will be translated to Kotlin and must pass against the same OpenAPI contract.

Spec ref: §5.1, §6.2 (Backend stack).
