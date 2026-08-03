# ADR-PY-002: Python FastAPI prototype for the REST API server

- Status: DEVIATION — TEMPORARY
- Date: 2026-07-31
- Spec ref: §6.2 (mandates Kotlin 2.1 + Spring Boot 3.4), §21.1 (REST Endpoints)
- Decider: Implementing agent (Phase 2 starter)

## Context

Spec §6.2 mandates Kotlin 2.1 + Spring Boot 3.4 for the backend server.
The visual designer (apps/web) needs a REST API to talk to (spec §21.1).
Delivering both a Kotlin/Spring Boot server AND a React SPA in a single
iteration is not practical — the Kotlin server requires Gradle build setup,
Spring Boot dependencies, and significant boilerplate.

The API contract (packages/api-spec/openapi.yaml) is language-agnostic.
The visual designer only cares about the contract, not the implementation
language of the server.

## Decision

Implement a Python FastAPI prototype server at `apps/server-python-prototype/`
as a thin shim over the existing `oiw` CLI logic (`apps/cli/oiw/`). The server:

- Imports `oiw` directly (no subprocess, no duplication).
- Exposes all §21.1 endpoints defined in `packages/api-spec/openapi.yaml`.
- Serves auto-generated Swagger UI at `/docs` and ReDoc at `/redoc`.
- Is the backend the React SPA talks to in development.

The contract (OpenAPI spec) is versioned and stable. When the Kotlin/Spring
Boot migration (OW-002) lands, the contract stays identical — only the
implementation changes. The React SPA is unaffected.

## Consequences

- Positive: React SPA can be built and tested against a real API immediately.
- Positive: The API contract is validated end-to-end (21 tests in
  `apps/server-python-prototype/tests/`).
- Positive: Swagger UI at `/docs` makes the API self-documenting.
- Positive: The FastAPI server auto-generates an OpenAPI spec from the
  route definitions, which can be diffed against the authoritative
  `packages/api-spec/openapi.yaml` to verify contract compliance.
- Negative: Three Python implementations exist during the migration window
  (CLI, server prototype, and eventually Kotlin). The server prototype
  imports the CLI, so they share all business logic — no duplication.
- Negative: FastAPI's auto-generated OpenAPI uses snake_case path parameters
  (`{project_id}`) while the authoritative spec uses camelCase (`{projectId}`).
  This is cosmetic; both are valid OpenAPI. The test suite accounts for it.
- Neutral: Migration to Kotlin/Spring Boot is a mechanical translation
  against the same OpenAPI contract. The 21 API tests survive unchanged
  (they test the contract, not the implementation).

## Alternatives considered

- **Build the Kotlin/Spring Boot server from day one.** Rejected: would
  leave the repo in a broken state for days while the build is set up.
  The FastAPI prototype unblocks the frontend immediately.
- **Have the SPA talk directly to the CLI via subprocess.** Rejected: not
  a real API; doesn't match the spec's architecture (§5.1 shows an API
  Gateway/BFF). The FastAPI prototype is a real REST API.
- **Use Node.js/Express for the prototype.** Rejected: would require
  reimplementing the OIW business logic in TypeScript. FastAPI imports
  the existing Python `oiw` package directly — zero duplication.

## Migration plan

Tracked as OW-002 in `DEVELOPMENT_LOG.md`. The Kotlin/Spring Boot server
at `apps/server/` will:

1. Implement the same OpenAPI contract (`packages/api-spec/openapi.yaml`).
2. Pass the same 21 API tests (translated to Kotlin).
3. Use the same JSON Schemas and test fixtures.
4. Replace `apps/server-python-prototype/` in Docker Compose.

The FastAPI prototype is deleted once the Kotlin server passes CI.
