"""Tenant adapter interface (WP-05 Task 2).

Spec ref: §18 (Tenant Connectivity), §18.3 (Adapter Interface).

A TenantAdapter abstracts the deployment API of a specific tenant
(SAP CI, or a mock for testing). All methods are async because real
tenant calls are network I/O.

The interface is deliberately minimal — it covers only the operations
the deployment pipeline needs:
  - connect / disconnect
  - get_artifact_version / get_artifact_digest (for drift detection)
  - upload_package (push a build artifact)
  - deploy (activate a version)
  - poll_deployment (wait for DEPLOYED state)
  - get_runtime_logs (for smoke test verification)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from ..environments import EnvironmentProfile


@dataclass
class ArtifactVersion:
    """Version info for an artifact on the tenant."""

    version: str
    deployed_at: datetime | None = None
    deployed_by: str | None = None
    digest: str | None = None


@dataclass
class UploadResult:
    """Result of uploading a package to the tenant."""

    success: bool
    version: str | None = None
    error: str | None = None
    uploaded_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DeploymentResult:
    """Result of deploying (activating) a version on the tenant."""

    success: bool
    deployment_id: str | None = None
    status: str = "UNKNOWN"  # DEPLOYED | FAILED | IN_PROGRESS
    error: str | None = None


@dataclass
class DeploymentStatus:
    """Polled deployment status."""

    state: str  # IN_PROGRESS | DEPLOYED | FAILED
    deployment_id: str
    message: str | None = None
    logs: list[str] = field(default_factory=list)


@dataclass
class LogEntry:
    """A runtime log entry from the tenant."""

    timestamp: datetime
    level: str  # INFO | WARN | ERROR
    message: str
    node_id: str | None = None


@runtime_checkable
class TenantAdapter(Protocol):
    """Abstract tenant adapter interface (spec §18.3).

    Implementations:
    - MockSapCiTenantAdapter: in-memory mock for testing
    - SapCiTenantAdapter: real SAP CI adapter (OW-010 placeholder)
    """

    async def connect(self, profile: EnvironmentProfile) -> None:
        """Establish a connection to the tenant using the profile's auth config."""
        ...

    async def get_artifact_version(self, package_id: str) -> ArtifactVersion | None:
        """Get the currently deployed version of a package, or None if not deployed."""
        ...

    async def get_artifact_digest(self, package_id: str) -> str | None:
        """Get the digest of the currently deployed artifact, or None.

        Used by drift detection to compare against the local build digest.
        """
        ...

    async def upload_package(self, package_id: str, archive: bytes, digest: str) -> UploadResult:
        """Upload a build artifact (ZIP) to the tenant."""
        ...

    async def deploy(self, package_id: str, version: str) -> DeploymentResult:
        """Deploy (activate) a specific version on the tenant."""
        ...

    async def poll_deployment(self, deployment_id: str) -> DeploymentStatus:
        """Poll the status of an in-progress deployment."""
        ...

    async def get_runtime_logs(self, package_id: str, since: datetime) -> list[LogEntry]:
        """Get runtime logs for a deployed package since a timestamp."""
        ...

    async def disconnect(self) -> None:
        """Clean up any connection state."""
        ...


__all__ = [
    "TenantAdapter",
    "ArtifactVersion",
    "UploadResult",
    "DeploymentResult",
    "DeploymentStatus",
    "LogEntry",
]
