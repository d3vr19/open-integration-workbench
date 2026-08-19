"""FastAPI application entry point.

Spec ref: §21.1 (REST Endpoints), §6.2 (OpenAPI 3.1 first).
ADR-PY-002: Python FastAPI prototype of the Kotlin/Spring Boot modular monolith.
"""

from __future__ import annotations

from fastapi import FastAPI

from . import __version__
from .config import server_version
from .models import HealthStatus
from .routes import (
    agent,
    archive,
    builds,
    diff,
    emg,
    flows,
    git,
    patches,
    projects,
    resources,
    simulate,
    tests,
    validate,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Open Integration Workbench API",
        description=(
            "REST API for Open Integration Workbench (OIW). "
            "Spec ref: §21.1. See packages/api-spec/openapi.yaml for the authoritative contract."
        ),
        version=server_version(),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Health check
    @app.get("/api/v1/health", response_model=HealthStatus, tags=["Projects"])
    def health() -> HealthStatus:
        return HealthStatus(status="ok", version=__version__)

    # Register routers
    app.include_router(projects.router)
    app.include_router(flows.router)
    app.include_router(patches.router)
    app.include_router(resources.router)
    app.include_router(simulate.router)
    app.include_router(agent.router)
    app.include_router(validate.router)
    app.include_router(tests.router)
    app.include_router(builds.router)
    app.include_router(diff.router)
    app.include_router(git.router)
    app.include_router(archive.router)
    app.include_router(emg.router)

    # WP-08 PR-3 / Track A-003: load the persisted EMG store at startup so
    # the EMG routes (`/api/v1/emg/stats`, `/api/v1/projects/{id}/emg/insights`)
    # serve real persisted corpus counts, not the empty in-memory test dict.
    # Safe to call: returns None on failure and the routes fall back to the
    # in-memory path.
    @app.on_event("startup")
    def _load_emg_store() -> None:
        emg.load_persisted_store()

    return app


app = create_app()


def main() -> None:
    """Entry point for the oiw-server console script.

    Security (spec §16.2): binds to 127.0.0.1 by default — the API has no
    authentication in local mode. Set OIW_HOST=0.0.0.0 for team mode (requires
    auth — not yet implemented, OW-005).
    """
    import os
    import warnings

    import uvicorn

    host = os.environ.get("OIW_HOST", "127.0.0.1")
    port = int(os.environ.get("OIW_SERVER_PORT", "8000"))
    if host != "127.0.0.1":
        warnings.warn(
            f"OIW server binding to {host} — this exposes the API without authentication. "
            "Only use this in trusted network environments (spec §16.2). "
            "Set OIW_HOST=127.0.0.1 to restrict to localhost.",
            stacklevel=2,
        )
    uvicorn.run(app, host=host, port=port)
