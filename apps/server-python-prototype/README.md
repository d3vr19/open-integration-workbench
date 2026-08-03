# OIW Server (Python FastAPI Prototype)

> **Phase 2 prototype. See ADR-PY-002 for the deviation rationale.**
> Production target: Kotlin/Spring Boot modular monolith at `apps/server/` (OW-002).

A thin REST API shim over the existing `oiw` CLI logic (`apps/cli/oiw/`).
Exposes the endpoints defined in `packages/api-spec/openapi.yaml` (spec §21.1).

## Run (development)

```bash
# From the repo root
pip install -e apps/cli
pip install -e apps/server-python-prototype

# Start the server (scans examples/ as the workspace)
uvicorn oiw_server.main:app --reload --port 8000

# Or with a custom workspace
OIW_WORKSPACE=/path/to/projects uvicorn oiw_server.main:app --reload --port 8000
```

The server reads projects from the directory pointed at `OIW_WORKSPACE`
(default: the `examples/` directory inside the repo).

## API docs

Once the server is running, open:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Endpoints

See `packages/api-spec/openapi.yaml` for the authoritative spec.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/projects` | List projects |
| GET | `/api/v1/projects/{id}` | Get project |
| GET | `/api/v1/projects/{id}/flows` | List flows |
| GET | `/api/v1/projects/{id}/flows/{flowId}` | Get flow IR + diagram |
| POST | `/api/v1/projects/{id}/validate` | Validate |
| POST | `/api/v1/projects/{id}/tests:run` | Run tests |
| POST | `/api/v1/projects/{id}/builds` | Build artifact |
| GET | `/api/v1/projects/{id}/git/status` | Git status |
| POST | `/api/v1/archive/inspect` | Safe archive inspect |

## Architecture

```
apps/server-python-prototype/oiw_server/
├── __init__.py
├── main.py              # FastAPI app + route registration
├── config.py            # Workspace resolution, env vars
├── models.py            # Pydantic response models
├── routes/
│   ├── __init__.py
│   ├── projects.py      # GET /projects, GET /projects/{id}
│   ├── flows.py         # GET /projects/{id}/flows, GET /flows/{flowId}
│   ├── validate.py      # POST /projects/{id}/validate
│   ├── tests.py         # POST /projects/{id}/tests:run
│   ├── builds.py        # POST /projects/{id}/builds
│   ├── git.py           # GET /projects/{id}/git/status
│   └── archive.py       # POST /archive/inspect
└── workspace.py         # Project discovery + caching
```

The server imports `oiw` (the CLI package) and calls its functions directly.
No subprocess; no duplication. When the Kotlin migration (OW-001, OW-002)
lands, the API contract stays identical — only the implementation changes.
