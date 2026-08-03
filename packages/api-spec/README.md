# OIW API Specification (OpenAPI 3.1)

> **Spec ref: §21.1 (REST Endpoints), §6.2 (OpenAPI 3.1 first).**

This is the authoritative API contract for Open Integration Workbench. All
clients — the visual designer (`apps/web`), the CLI, the MCP server, and
external agents — talk to the server through this contract.

## Files

- `openapi.yaml` — the OpenAPI 3.1 document.

## Versioning

The API path prefix `/api/v1` is versioned. Breaking changes require a new
prefix (`/api/v2`) and a migration guide. Additive changes (new endpoints,
new optional fields) are allowed within `/api/v1`.

## Implementation

| Implementation | Status | Location |
|----------------|--------|----------|
| Python FastAPI prototype | ACTIVE | `apps/server-python-prototype/` (see ADR-PY-002) |
| Kotlin/Spring Boot | PLANNED | `apps/server/` (Phase 2+; see ADR-PY-001, OW-002) |

The contract is implementation-agnostic. The FastAPI prototype and the
future Kotlin server MUST both satisfy this spec. The test suite in
`apps/server-python-prototype/tests/` validates the contract.

## Endpoints (summary)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/projects` | List projects in workspace |
| GET | `/api/v1/projects/{projectId}` | Get project manifest |
| GET | `/api/v1/projects/{projectId}/flows` | List flows |
| GET | `/api/v1/projects/{projectId}/flows/{flowId}` | Get flow IR + diagram |
| POST | `/api/v1/projects/{projectId}/validate` | Run validation pipeline |
| POST | `/api/v1/projects/{projectId}/tests:run` | Run flow tests |
| POST | `/api/v1/projects/{projectId}/builds` | Build artifact |
| GET | `/api/v1/projects/{projectId}/git/status` | Git status + last build digest |
| POST | `/api/v1/archive/inspect` | Safe archive inspection |
| GET | `/api/v1/health` | Health check |

## Generating clients

```bash
# Install openapi-generator
npm install @openapitools/openapi-generator-cli -g

# Generate a TypeScript client for apps/web
openapi-generator-cli generate \
  -i packages/api-spec/openapi.yaml \
  -g typescript-fetch \
  -o packages/api-client/
```

(Client generation is tracked as OW-015; the current SPA uses a hand-written
fetch-based client.)
