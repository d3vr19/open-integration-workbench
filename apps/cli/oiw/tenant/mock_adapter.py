"""Mock SAP CI tenant adapter (WP-05 Task 2).

In-memory mock for local/CI testing. Persists state to
`.oiw/mock-tenant/{profile}/` so deployments survive across runs.

Simulates:
  - Upload validation (archive must be non-empty bytes)
  - Deployment latency (configurable, default 0.5s)
  - Deployment failures (configurable scenarios)
  - Deployment state polling (IN_PROGRESS → DEPLOYED)
  - Runtime logs (empty by default)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..environments import EnvironmentProfile
from .adapter import (
    ArtifactVersion,
    DeploymentResult,
    DeploymentStatus,
    LogEntry,
    UploadResult,
)


class MockTenantError(Exception):
    """Raised by the mock adapter when a configured failure scenario triggers."""


class MockSapCiTenantAdapter:
    """In-memory mock SAP CI tenant adapter.

    State is persisted to `.oiw/mock-tenant/{profile_name}/state.json`
    so deployments survive across runs (necessary for the deployment
    state machine tests).

    Configurable failure scenarios (set via constructor or env vars):
    - fail_auth: connect() raises MockTenantError
    - fail_upload: upload_package() always fails
    - fail_deploy: deploy() always fails
    - deploy_timeout: deploy() never reaches DEPLOYED
    """

    def __init__(
        self,
        state_dir: Path | str | None = None,
        deploy_latency_seconds: float = 0.1,
        failure_scenario: str | None = None,
    ):
        self._state_dir = Path(state_dir) if state_dir else None
        self._deploy_latency = deploy_latency_seconds
        self._failure_scenario = failure_scenario
        self._connected = False
        self._profile: EnvironmentProfile | None = None
        self._state: dict[str, Any] = {}
        self._deployments: dict[str, dict[str, Any]] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self, profile: EnvironmentProfile) -> None:
        """Connect to the mock tenant. Loads persisted state if available."""
        if self._failure_scenario == "fail_auth":
            raise MockTenantError("mock: authentication failed (configured scenario)")
        self._profile = profile
        self._connected = True
        if self._state_dir is not None:
            self._state_dir = self._state_dir / profile.name
            self._state_dir.mkdir(parents=True, exist_ok=True)
            self._load_state()

    async def get_artifact_version(self, package_id: str) -> ArtifactVersion | None:
        """Get the deployed version from persisted state."""
        if not self._connected:
            raise MockTenantError("not connected")
        artifacts = self._state.get("artifacts", {})
        info = artifacts.get(package_id)
        if info is None:
            return None
        return ArtifactVersion(
            version=info.get("version", "unknown"),
            deployed_at=datetime.fromisoformat(info["deployed_at"]) if info.get("deployed_at") else None,
            deployed_by=info.get("deployed_by"),
            digest=info.get("digest"),
        )

    async def get_artifact_digest(self, package_id: str) -> str | None:
        """Get the deployed artifact's digest."""
        version = await self.get_artifact_version(package_id)
        return version.digest if version else None

    async def upload_package(self, package_id: str, archive: bytes, digest: str) -> UploadResult:
        """Upload a build artifact. Validates the archive is non-empty."""
        if not self._connected:
            raise MockTenantError("not connected")
        if self._failure_scenario == "fail_upload":
            return UploadResult(success=False, error="mock: upload failed (configured scenario)")
        if not archive:
            return UploadResult(success=False, error="archive is empty")
        version = f"v-{uuid.uuid4().hex[:8]}"
        self._state.setdefault("artifacts", {})[package_id] = {
            "version": version,
            "digest": digest,
            "uploaded_at": datetime.now(tz=UTC).isoformat(),
            "deployed_at": None,
            "deployed_by": None,
        }
        self._persist_state()
        return UploadResult(success=True, version=version)

    async def deploy(self, package_id: str, version: str) -> DeploymentResult:
        """Deploy a version. Simulates latency and optional failures."""
        if not self._connected:
            raise MockTenantError("not connected")
        if self._failure_scenario == "fail_deploy":
            return DeploymentResult(
                success=False, status="FAILED", error="mock: deploy failed (configured scenario)"
            )
        # Simulate deployment latency
        await asyncio.sleep(self._deploy_latency)
        deployment_id = f"dep-{uuid.uuid4().hex[:8]}"
        if self._failure_scenario == "deploy_timeout":
            # Deployment never completes — stays IN_PROGRESS
            self._deployments[deployment_id] = {
                "package_id": package_id,
                "version": version,
                "state": "IN_PROGRESS",
            }
            self._persist_state()
            return DeploymentResult(success=True, deployment_id=deployment_id, status="IN_PROGRESS")
        # Normal: deploy succeeds
        self._deployments[deployment_id] = {
            "package_id": package_id,
            "version": version,
            "state": "DEPLOYED",
            "deployed_at": datetime.now(tz=UTC).isoformat(),
        }
        # Update artifact state
        artifacts = self._state.setdefault("artifacts", {})
        if package_id in artifacts:
            artifacts[package_id]["deployed_at"] = datetime.now(tz=UTC).isoformat()
            artifacts[package_id]["version"] = version
        self._persist_state()
        return DeploymentResult(success=True, deployment_id=deployment_id, status="DEPLOYED")

    async def poll_deployment(self, deployment_id: str) -> DeploymentStatus:
        """Poll deployment status. For the mock, the state is already final."""
        if not self._connected:
            raise MockTenantError("not connected")
        dep = self._deployments.get(deployment_id)
        if dep is None:
            return DeploymentStatus(
                state="FAILED", deployment_id=deployment_id, message="deployment not found"
            )
        return DeploymentStatus(
            state=dep["state"],
            deployment_id=deployment_id,
            message="mock: deployment status",
        )

    async def get_runtime_logs(self, package_id: str, since: datetime) -> list[LogEntry]:
        """Return empty logs (mock tenant has no runtime activity)."""
        if not self._connected:
            raise MockTenantError("not connected")
        return []

    async def disconnect(self) -> None:
        """Disconnect and persist state."""
        self._persist_state()
        self._connected = False
        self._profile = None

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        """Load persisted state from disk."""
        if self._state_dir is None:
            return
        state_file = self._state_dir / "state.json"
        if state_file.is_file():
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                self._state = data.get("artifacts", {})
                self._deployments = data.get("deployments", {})
            except (json.JSONDecodeError, KeyError):
                self._state = {}
                self._deployments = {}

    def _persist_state(self) -> None:
        """Persist state to disk."""
        if self._state_dir is None:
            return
        self._state_dir.mkdir(parents=True, exist_ok=True)
        state_file = self._state_dir / "state.json"
        state_file.write_text(
            json.dumps(
                {"artifacts": self._state, "deployments": self._deployments},
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all in-memory state (for tests)."""
        self._state = {}
        self._deployments = {}


__all__ = ["MockSapCiTenantAdapter", "MockTenantError"]
