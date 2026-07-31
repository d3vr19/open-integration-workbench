"""FastAPI application entry point.

Spec ref: §21.1 (REST Endpoints), §6.2 (OpenAPI 3.1 first).
ADR-PY-002: Python FastAPI prototype of the Kotlin/Spring Boot modular monolith.
"""

from __future__ import annotations

from fastapi import FastAPI

from . import __version__
from .config import server_version
from .models import HealthStatus
from .routes import archive, builds, diff, flows, git, patches, projects, resources, simulate, tests, validate


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
    app.include_router(validate.router)
    app.include_router(tests.router)
    app.include_router(builds.router)
    app.include_router(diff.router)
    app.include_router(git.router)
    app.include_router(archive.router)

    return app


app = create_app()
