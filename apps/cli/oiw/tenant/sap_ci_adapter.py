"""Real SAP Cloud Integration tenant adapter (WP-08 Track 0).

Spec ref: §18 (Tenant Connectivity), §18.3 (Adapter Interface).
WP-08 reference: Track 0 — BTP Tenant Smoke. Track C — Learn From Existing Tenant Artifacts.

Scope of THIS implementation (read-only, GET-only):

  - connect():                validate Basic auth by hitting the service root.
  - list_packages():          GET /IntegrationPackages
  - list_artifacts(pkg_id):   GET /IntegrationPackages('{id}')/IntegrationDesigntimeArtifacts
  - download_artifact(id, ver): GET /IntegrationDesigntimeArtifacts(Id='{id}',Version='{ver}')/$value
  - get_artifact_version(pkg_id): latest version of the first artifact in a package (drift hook)
  - get_artifact_digest(pkg_id): sha256 of the latest artifact ZIP bytes (drift hook)

Operations that MUTATE the tenant are intentionally NOT implemented:
  - upload_package(), deploy(), poll_deployment(), get_runtime_logs()

This is deliberate. Per WP-08 §C-004 ("Track C is GET-only. No
upload_package, no DeployIntegrationArtifact. The tenant is a library,
not a scratchpad.") we do not mutate the tenant in this track. Write
operations remain NotImplementedError so any caller that hits them
fails loudly instead of silently corrupting tenant state.

Auth: HTTP Basic with S-user credentials resolved from env vars:
  - OIW_TENANT_URL            (overrides profile.tenant_url)
  - OIW_TENANT_USER           (Basic auth username; also accepts OIW_CRED_<ref>_USERNAME)
  - OIW_TENANT_PASSWORD       (Basic auth password; also accepts OIW_CRED_<ref>_PASSWORD)
  - OIW_USE_REAL_TENANT=1     (enables this adapter in build_tenant_adapter())

The legacy OAuth2 client-credentials path documented in WP-08 T0-001
remains a future task; Basic auth against the public OData API is
sufficient for read-only inventory + artifact download and is what
S-user credentials (S0026012658-style IDs) are issued for.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from ..environments import EnvironmentProfile
from .adapter import (
    ArtifactVersion,
    DeploymentResult,
    DeploymentStatus,
    LogEntry,
    UploadResult,
)

if TYPE_CHECKING:
    from .mock_adapter import MockSapCiTenantAdapter


class SapCiTenantError(Exception):
    """Raised by the real adapter on tenant-side errors (HTTP 4xx/5xx, auth failure)."""


@dataclass
class TenantPackageSummary:
    """Lightweight summary of an IntegrationPackage on the tenant."""

    id: str
    name: str
    version: str
    mode: str  # EDIT_ALLOWED | READ_ONLY | ...
    modified_by: str | None = None
    resource_id: str | None = None


@dataclass
class TenantArtifactSummary:
    """Lightweight summary of an IntegrationDesigntimeArtifact on the tenant."""

    id: str
    name: str
    version: str
    package_id: str | None = None
    media_src: str | None = None  # the absolute $value URL


class SapCiTenantAdapter:
    """Real SAP Cloud Integration tenant adapter (read-only, Basic auth).

    Use `build_tenant_adapter()` to construct this from env vars, or
    instantiate directly with explicit credentials in tests.

    The adapter is safe to use against a production tenant in the
    current scope: every network call is a GET. Write operations
    (upload_package, deploy) raise NotImplementedError.
    """

    def __init__(
        self,
        tenant_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        *,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ):
        self._tenant_url = (tenant_url or "").rstrip("/")
        self._username = username or ""
        self._password = password or ""
        self._timeout = timeout_seconds
        self._client = client  # injected for tests (httpx.MockTransport)
        self._owns_client = client is None
        self._connected = False
        self._profile: EnvironmentProfile | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tenant_url(self) -> str:
        return self._tenant_url

    def _basic_auth_header(self) -> dict[str, str]:
        if not self._username or not self._password:
            raise SapCiTenantError(
                "SapCiTenantAdapter: missing credentials. Set OIW_TENANT_USER and "
                "OIW_TENANT_PASSWORD (or OIW_CRED_<ref>_USERNAME/_PASSWORD)."
            )
        token = base64.b64encode(f"{self._username}:{self._password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _resolve_credentials_from_env(self, profile: EnvironmentProfile) -> None:
        """Fill in missing tenant_url / username / password from env vars.

        Precedence:
          1. Explicit constructor args (already set on self).
          2. OIW_TENANT_URL / OIW_TENANT_USER / OIW_TENANT_PASSWORD.
          3. profile.tenant_url + OIW_CRED_<ref>_USERNAME / _PASSWORD,
             where <ref> is profile.auth.credentialRef uppercased and
             non-alphanumerics replaced with _.
        """
        if not self._tenant_url:
            self._tenant_url = (os.environ.get("OIW_TENANT_URL") or (profile.tenant_url or "")).rstrip("/")
        if not self._username:
            self._username = os.environ.get("OIW_TENANT_USER", "")
        if not self._password:
            self._password = os.environ.get("OIW_TENANT_PASSWORD", "")

        # Fall back to credential-ref-keyed env vars (matches WP-08 T0-001 doc)
        ref = (profile.auth.credential_ref if profile.auth else None) or ""
        ref_key = "".join(c if c.isalnum() else "_" for c in ref.upper())
        if not self._username and ref:
            self._username = os.environ.get(f"OIW_CRED_{ref_key}_USERNAME", "")
        if not self._password and ref:
            self._password = os.environ.get(f"OIW_CRED_{ref_key}_PASSWORD", "")

    async def connect(self, profile: EnvironmentProfile) -> None:
        """Validate credentials by hitting the OData service root."""
        self._resolve_credentials_from_env(profile)
        if not self._tenant_url:
            raise SapCiTenantError(
                "tenant_url not configured: set OIW_TENANT_URL or "
                "spec.spec.tenantUrl in the environment profile."
            )
        if not self._username or not self._password:
            raise SapCiTenantError(
                "credentials not configured: set OIW_TENANT_USER and "
                "OIW_TENANT_PASSWORD (or OIW_CRED_<ref>_USERNAME/_PASSWORD)."
            )
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._tenant_url,
                timeout=self._timeout,
                follow_redirects=True,
            )
        self._profile = profile
        # Validate by issuing a HEAD on the service root. SAP CI returns 200
        # with a small JSON service document for valid Basic auth.
        try:
            resp = await self._client.get(
                "/", headers={**self._basic_auth_header(), "Accept": "application/json"}
            )
        except httpx.HTTPError as exc:
            raise SapCiTenantError(f"tenant unreachable at {self._tenant_url}: {exc}") from exc
        if resp.status_code == 401:
            raise SapCiTenantError(
                "tenant rejected credentials (HTTP 401). Check OIW_TENANT_USER / OIW_TENANT_PASSWORD."
            )
        if resp.status_code >= 400:
            raise SapCiTenantError(
                f"tenant returned HTTP {resp.status_code} on service root: " f"{resp.text[:200]}"
            )
        self._connected = True

    async def disconnect(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None
        self._connected = False

    # ------------------------------------------------------------------
    # Read operations — list / download
    # ------------------------------------------------------------------

    async def list_packages(self, top: int = 50) -> list[TenantPackageSummary]:
        """List IntegrationPackages on the tenant (OData $top=N)."""
        self._require_connected()
        resp = await self._client.get(
            "/IntegrationPackages",
            params={"$top": top},
            headers={**self._basic_auth_header(), "Accept": "application/json"},
        )
        self._raise_for_status(resp, "list_packages")
        data = resp.json()
        results = data.get("d", {}).get("results", []) if isinstance(data, dict) else data.get("value", [])
        return [
            TenantPackageSummary(
                id=p.get("Id", ""),
                name=p.get("Name") or "",
                version=str(p.get("Version") or ""),
                mode=p.get("Mode") or "",
                modified_by=p.get("ModifiedBy"),
                resource_id=p.get("ResourceId"),
            )
            for p in results
        ]

    async def list_artifacts(self, package_id: str, top: int = 100) -> list[TenantArtifactSummary]:
        """List IntegrationDesigntimeArtifacts in a package."""
        self._require_connected()
        resp = await self._client.get(
            f"/IntegrationPackages('{package_id}')/IntegrationDesigntimeArtifacts",
            params={"$top": top},
            headers={**self._basic_auth_header(), "Accept": "application/json"},
        )
        self._raise_for_status(resp, "list_artifacts")
        data = resp.json()
        results = data.get("d", {}).get("results", []) if isinstance(data, dict) else data.get("value", [])
        out: list[TenantArtifactSummary] = []
        for a in results:
            md = a.get("__metadata", {}) or {}
            out.append(
                TenantArtifactSummary(
                    id=a.get("Id", ""),
                    name=a.get("Name") or "",
                    version=str(a.get("Version") or ""),
                    package_id=package_id,
                    media_src=md.get("media_src"),
                )
            )
        return out

    async def download_artifact(self, artifact_id: str, version: str) -> bytes:
        """Download an artifact's $value (returns ZIP bytes)."""
        self._require_connected()
        # SAP CI's OData key for an artifact is (Id, Version). URL-encode the
        # parens-commas the way SAP CI expects: no extra quoting.
        url = f"/IntegrationDesigntimeArtifacts(Id='{artifact_id}',Version='{version}')/$value"
        resp = await self._client.get(
            url,
            headers={**self._basic_auth_header(), "Accept": "application/zip, application/octet-stream"},
        )
        self._raise_for_status(resp, "download_artifact")
        return resp.content

    # ------------------------------------------------------------------
    # Drift hooks (read-only; satisfy the TenantAdapter protocol)
    # ------------------------------------------------------------------

    async def get_artifact_version(self, package_id: str) -> ArtifactVersion | None:
        """Return the latest artifact version in a package, or None if empty."""
        artifacts = await self.list_artifacts(package_id, top=1)
        if not artifacts:
            return None
        a = artifacts[0]
        return ArtifactVersion(version=a.version, deployed_at=None, deployed_by=None, digest=None)

    async def get_artifact_digest(self, package_id: str) -> str | None:
        """Compute sha256 of the latest artifact ZIP for drift detection."""
        artifacts = await self.list_artifacts(package_id, top=1)
        if not artifacts:
            return None
        a = artifacts[0]
        blob = await self.download_artifact(a.id, a.version)
        return "sha256:" + hashlib.sha256(blob).hexdigest()

    # ------------------------------------------------------------------
    # Write operations — intentionally NOT implemented (WP-08 §C-004)
    # ------------------------------------------------------------------

    async def upload_package(self, package_id: str, archive: bytes, digest: str) -> UploadResult:
        raise NotImplementedError(
            "SapCiTenantAdapter.upload_package is intentionally not implemented in WP-08 "
            "Track 0/C. The tenant is read-only in this track (WP-08 §C-004). "
            "Track D-004 will introduce a scoped, opt-in upload path for the held-out "
            "test artifact only."
        )

    async def deploy(self, package_id: str, version: str) -> DeploymentResult:
        raise NotImplementedError(
            "SapCiTenantAdapter.deploy is intentionally not implemented in WP-08 Track 0/C "
            "(WP-08 §C-004: no DeployIntegrationArtifact)."
        )

    async def poll_deployment(self, deployment_id: str) -> DeploymentStatus:
        raise NotImplementedError("SapCiTenantAdapter.poll_deployment is not implemented (no deploy path).")

    async def get_runtime_logs(self, package_id: str, since: object) -> list[LogEntry]:
        raise NotImplementedError(
            "SapCiTenantAdapter.get_runtime_logs is not implemented in WP-08 Track 0/C."
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_connected(self) -> None:
        if not self._connected or self._client is None:
            raise SapCiTenantError("adapter not connected — call connect(profile) first")

    def _raise_for_status(self, resp: httpx.Response, op: str) -> None:
        if resp.status_code < 400:
            return
        # Try to extract SAP OData error message
        msg = f"tenant returned HTTP {resp.status_code} for {op}"
        try:
            body = resp.json()
            err = body.get("error", {})
            inner = err.get("message", {})
            if isinstance(inner, dict):
                msg += f": {err.get('code', '')} {inner.get('value', '')}"
            elif isinstance(inner, str):
                msg += f": {inner}"
        except Exception:
            msg += f": {resp.text[:200]}"
        raise SapCiTenantError(msg)


def build_tenant_adapter(
    use_real: bool | None = None,
    *,
    tenant_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
) -> SapCiTenantAdapter | MockSapCiTenantAdapter:
    """Factory: return the real adapter when OIW_USE_REAL_TENANT=1, else the mock.

    Per WP-08 §10 "What Not To Do": never default OIW_USE_REAL_TENANT=1 in CI.
    CI stays on the mock; the real adapter is for local/tenant work.
    """
    if use_real is None:
        use_real = os.environ.get("OIW_USE_REAL_TENANT", "").strip() in {"1", "true", "True", "yes"}
    if use_real:
        return SapCiTenantAdapter(tenant_url=tenant_url, username=username, password=password)
    # Lazy import to avoid the mock's state-dir defaulting in tests
    from .mock_adapter import MockSapCiTenantAdapter

    return MockSapCiTenantAdapter()


__all__ = [
    "SapCiTenantAdapter",
    "SapCiTenantError",
    "TenantPackageSummary",
    "TenantArtifactSummary",
    "build_tenant_adapter",
]
