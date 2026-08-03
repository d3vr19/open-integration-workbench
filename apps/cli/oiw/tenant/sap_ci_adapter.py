"""SAP CI tenant adapter stub (WP-05 Task 2).

The real SAP CI adapter requires tenant access (OW-010). This stub
raises NotImplementedError for all methods so callers get a clear
error if they try to use it before OW-010 is resolved.

Use MockSapCiTenantAdapter for all testing.
"""

from __future__ import annotations

from ..environments import EnvironmentProfile
from .adapter import (
    ArtifactVersion,
    DeploymentResult,
    DeploymentStatus,
    LogEntry,
    UploadResult,
)

_NOT_IMPLEMENTED_MSG = (
    "SAP CI tenant adapter not yet implemented. See OW-010. " "Use MockSapCiTenantAdapter for testing."
)


class SapCiTenantAdapter:
    """Real SAP CI adapter — placeholder until OW-010 (tenant access) is resolved.

    All methods raise NotImplementedError. When OW-010 is resolved, this
    class will be implemented with real OAuth2 client-credentials auth,
    SAP CI REST API calls, and proper error handling.
    """

    async def connect(self, profile: EnvironmentProfile) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def get_artifact_version(self, package_id: str) -> ArtifactVersion | None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def get_artifact_digest(self, package_id: str) -> str | None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def upload_package(self, package_id: str, archive: bytes, digest: str) -> UploadResult:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def deploy(self, package_id: str, version: str) -> DeploymentResult:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def poll_deployment(self, deployment_id: str) -> DeploymentStatus:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def get_runtime_logs(self, package_id: str, since: object) -> list[LogEntry]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def disconnect(self) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)


__all__ = ["SapCiTenantAdapter"]
