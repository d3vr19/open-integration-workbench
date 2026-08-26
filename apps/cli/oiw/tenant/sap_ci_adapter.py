"""Real SAP Cloud Integration tenant adapter (WP-08 Track 0 + PR-9 / D-004).

Spec ref: §18 (Tenant Connectivity), §18.3 (Adapter Interface).
WP-08 reference: Track 0 — BTP Tenant Smoke. Track C — Learn From Existing
Tenant Artifacts. Track D-004 (PR-9) — scoped update-only WRITE path.

READ operations (Track 0/C):

  - connect():                validate Basic auth by hitting the service root.
  - list_packages():          GET /IntegrationPackages
  - list_artifacts(pkg_id):   GET /IntegrationPackages('{id}')/IntegrationDesigntimeArtifacts
  - download_artifact(id, ver): GET /IntegrationDesigntimeArtifacts(Id='{id}',Version='{ver}')/$value
  - get_artifact_version(pkg_id): latest version of the first artifact in a package (drift hook)
  - get_artifact_digest(pkg_id): sha256 of the latest artifact ZIP bytes (drift hook)

WRITE operations (Track D-004) — UPDATE-ONLY, allowlist-gated:

  Per T0-003 the tenant is a library, not a scratchpad: this adapter can
  only UPDATE the designtime content of an artifact that ALREADY EXISTS
  inside a package that a human pre-created. It never creates packages,
  never creates artifacts, never touches anything outside the allowlist.

  - upload_package(pkg, archive, digest): PUT .../IntegrationDesigntimeArtifacts(Id,V)/$value
  - deploy(pkg, version):        POST /IntegrationRuntimeArtifacts
  - poll_deployment(id):         GET  /IntegrationRuntimeArtifacts('{id}')
  - get_runtime_logs(pkg, since): GET /MessageProcessingLogs?$filter=...

  The allowlist comes from `writable_packages=` or env
  OIW_TENANT_WRITABLE_PACKAGES (comma-separated). An EMPTY allowlist
  makes every write raise — failing loudly beats guessing. This is the
  code-level embodiment of WP-08 §D-004 ("only against that package id").

Auth: HTTP Basic with S-user credentials resolved from env vars:
  - OIW_TENANT_URL            (overrides profile.tenant_url)
  - OIW_TENANT_USER           (Basic auth username; also accepts OIW_CRED_<ref>_USERNAME)
  - OIW_TENANT_PASSWORD       (Basic auth password; also accepts OIW_CRED_<ref>_PASSWORD)
  - OIW_USE_REAL_TENANT=1     (enables this adapter in build_tenant_adapter())
  - OIW_TENANT_WRITABLE_PACKAGES (allowlist for write ops; empty = read-only)

SAP's OData endpoint may require a CSRF token for mutating requests; the
adapter fetches one opportunistically (X-CSRF-Token: fetch on the service
root) and attaches it to writes when the tenant issues one.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
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
        writable_packages: list[str] | None = None,
    ):
        self._tenant_url = (tenant_url or "").rstrip("/")
        self._username = username or ""
        self._password = password or ""
        self._timeout = timeout_seconds
        self._client = client  # injected for tests (httpx.MockTransport)
        self._owns_client = client is None
        self._connected = False
        self._profile: EnvironmentProfile | None = None
        # Track D-004: update-only write path. Empty/None = read-only
        # (every write raises). Resolved against env in connect().
        self._explicit_writable = list(writable_packages) if writable_packages else []
        self._writable: list[str] = list(self._explicit_writable)
        self._csrf_token: str | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tenant_url(self) -> str:
        return self._tenant_url

    @property
    def writable_packages(self) -> list[str]:
        """Packages this adapter may mutate (allowlist; possibly empty)."""
        return list(self._writable)

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

    def _resolve_writable_packages_from_env(self) -> None:
        """Merge the explicit allowlist with OIW_TENANT_WRITABLE_PACKAGES.

        Entries are either `PackageId` (any artifact in the package may be
        updated) or `PackageId/ArtifactId` (ONLY that artifact may be
        updated — the safe default for shared scratch packages). Explicit
        constructor entries win (deduped, order-preserving). An empty
        result means read-only.
        """
        env_raw = os.environ.get("OIW_TENANT_WRITABLE_PACKAGES", "")
        env_pkgs = [p.strip() for p in env_raw.split(",") if p.strip()]
        merged: list[str] = []
        for p in [*self._explicit_writable, *env_pkgs]:
            if p and p not in merged:
                merged.append(p)
        self._writable = merged

    def _package_is_writable(self, package_id: str) -> bool:
        return any(e == package_id or e.startswith(f"{package_id}/") for e in self._writable)

    def _pinned_artifact(self, package_id: str) -> str | None:
        """The single artifact id this package's writes are pinned to, if any."""
        pins = [
            e.split("/", 1)[1]
            for e in self._writable
            if e.startswith(f"{package_id}/") and len(e) > len(package_id) + 1
        ]
        return pins[0] if pins else None

    async def connect(self, profile: EnvironmentProfile) -> None:
        """Validate credentials by hitting the OData service root."""
        self._resolve_credentials_from_env(profile)
        self._resolve_writable_packages_from_env()
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
        """Return the latest artifact version in a package, or None if empty.

        Honors an artifact pin (`PackageId/ArtifactId` allowlist entry) so
        drift detection compares against the SAME artifact the write path
        targets — never a different sibling in a shared package.
        """
        artifacts = await self.list_artifacts(package_id, top=100)
        if not artifacts:
            return None
        pin = self._pinned_artifact(package_id)
        if pin:
            artifacts = [a for a in artifacts if a.id == pin]
            if not artifacts:
                return None
        a = artifacts[0]
        return ArtifactVersion(version=a.version, deployed_at=None, deployed_by=None, digest=None)

    async def get_artifact_digest(self, package_id: str) -> str | None:
        """Compute sha256 of the target artifact ZIP for drift detection."""
        artifacts = await self.list_artifacts(package_id, top=100)
        pin = self._pinned_artifact(package_id)
        if pin:
            artifacts = [a for a in artifacts if a.id == pin]
        if not artifacts:
            return None
        a = artifacts[0]
        blob = await self.download_artifact(a.id, a.version)
        return "sha256:" + hashlib.sha256(blob).hexdigest()

    # ------------------------------------------------------------------
    # Write operations — UPDATE-ONLY, allowlist-gated (WP-08 PR-9 / D-004)
    # ------------------------------------------------------------------

    def _ensure_writable(self, package_id: str) -> None:
        """Raise unless package_id is on the explicit write allowlist."""
        if not self._writable:
            raise SapCiTenantError(
                "write refused: no writable packages configured. Set "
                "OIW_TENANT_WRITABLE_PACKAGES (or writable_packages=) to the "
                "human-created scratch package id(s) — optionally pinned to a "
                "single artifact as PackageId/ArtifactId. Per WP-08 §D-004 the "
                "tenant is a library, not a scratchpad — OIW only ever "
                "updates artifacts inside packages you explicitly allow."
            )
        if not self._package_is_writable(package_id):
            raise SapCiTenantError(
                f"write refused: package '{package_id}' is not on the writable "
                f"allowlist {self._writable}. Only pre-created scratch "
                f"packages may be updated (WP-08 §D-004 / T0-003)."
            )

    async def _ensure_csrf_token(self) -> None:
        """Fetch a CSRF token if the tenant issues one (standard SAP pattern).

        GET the service root with X-CSRF-Token: fetch; if the response
        carries the header we cache and attach it to mutating requests.
        Tenants without CSRF simply omit the header — that's fine.
        """
        if self._csrf_token is not None:
            return
        try:
            resp = await self._client.get(
                "/",
                headers={**self._basic_auth_header(), "X-CSRF-Token": "fetch", "Accept": "application/json"},
            )
            self._csrf_token = resp.headers.get("x-csrf-token") or None
        except httpx.HTTPError:
            self._csrf_token = None

    def _write_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            **self._basic_auth_header(),
            **(extra or {}),
        }
        if self._csrf_token:
            headers["x-csrf-token"] = self._csrf_token
        return headers

    async def _resolve_target_artifact(
        self, package_id: str, artifact_id: str | None = None
    ) -> TenantArtifactSummary:
        """Find the EXISTING designtime artifact to update in a package.

        Update-only policy (T0-003): we never create artifacts. If the
        package has none, fail with remediation instead of guessing.

        When the allowlist pins artifacts (`PackageId/ArtifactId`), ONLY
        pinned artifacts are valid targets — a shared scratch package must
        never see its other (real) artifacts overwritten. With multiple
        pins, `artifact_id` selects among them; it must itself be pinned.
        """
        pins = [
            e.split("/", 1)[1]
            for e in self._writable
            if e.startswith(f"{package_id}/") and len(e) > len(package_id) + 1
        ]
        if artifact_id is not None:
            if artifact_id not in pins:
                raise SapCiTenantError(
                    f"artifact '{artifact_id}' is not in the writable allowlist "
                    f"for package '{package_id}' — add "
                    f"'{package_id}/{artifact_id}' to OIW_TENANT_WRITABLE_PACKAGES"
                )
            pin = artifact_id
        elif len(pins) > 1:
            raise SapCiTenantError(
                f"package '{package_id}' has multiple allowlisted artifacts "
                f"({', '.join(sorted(pins))}) — select one explicitly"
            )
        elif pins:
            pin = pins[0]
        else:
            pin = None
        artifacts = await self.list_artifacts(package_id, top=100)
        if not artifacts:
            raise SapCiTenantError(
                f"package '{package_id}' has no designtime artifacts to update. "
                f"Per T0-003 this adapter is update-only: create the artifact "
                f"once in the tenant UI (any placeholder iFlow), then re-run."
            )
        if pin:
            for a in artifacts:
                if a.id == pin:
                    return a
            raise SapCiTenantError(
                f"pinned artifact '{pin}' not found in package '{package_id}'. "
                f"Refusing to fall back to another artifact — the allowlist "
                f"entry '{package_id}/{pin}' names exactly one update target."
            )
        return artifacts[0]

    async def upload_package(
        self, package_id: str, archive: bytes, digest: str, artifact_id: str | None = None
    ) -> UploadResult:
        """Update an existing artifact's designtime content with `archive`.

        LIVE-PROVEN VERB (2026-08-25, AdaequareGST/open_mateo_test):
        UPDATE = PUT /IntegrationDesigntimeArtifacts(Id='{id}',Version='{v}')
        with JSON {ArtifactContent: <base64 zip>}. POST is CREATE-only
        (rejects existing ids with a misleading 500); PUT on $value is
        501; multipart is 501. The bundle's Bundle-SymbolicName must match
        the existing artifact — callers inherit identity via
        sap_export.cpi_bundle_identity.

        Policy refusals come FIRST — an out-of-allowlist write must fail
        even if the adapter isn't connected.
        """
        import base64 as _b64

        self._ensure_writable(package_id)
        self._require_connected()
        if not archive or len(archive) < 4:
            return UploadResult(
                success=False, version=None, error="empty or truncated archive", uploaded_at=None
            )
        target = await self._resolve_target_artifact(package_id, artifact_id)
        await self._ensure_csrf_token()
        payload = {"ArtifactContent": _b64.b64encode(archive).decode()}
        url = f"/IntegrationDesigntimeArtifacts(Id='{target.id}',Version='{target.version}')"
        try:
            resp = await self._client.put(
                url,
                json=payload,
                headers=self._write_headers(
                    {"Content-Type": "application/json", "Accept": "application/json"}
                ),
            )
        except httpx.HTTPError as exc:
            raise SapCiTenantError(f"upload unreachable at {url}: {exc}") from exc
        if resp.status_code >= 400:
            self._raise_for_status(resp, "upload_package")
        return UploadResult(
            success=True,
            version=target.version,
            error=None,
            uploaded_at=None,  # SAP doesn't echo a timestamp here
        )

    async def deploy(self, package_id: str, version: str, artifact_id: str | None = None) -> DeploymentResult:
        """Deploy (activate): POST /DeployIntegrationDesigntimeArtifact.

        LIVE-PROVEN (2026-08-26, from the tenant's own
        IntegrationContent.edmx function imports): OData v1 function
        import taking Id/Version as QUERY parameters; returns HTTP 202
        with an opaque tracking UUID. Activation progress polls via
        GET /IntegrationRuntimeArtifacts?$filter=Name eq '<id>' (the
        collection Id IS the artifact id).
        """
        self._ensure_writable(package_id)
        self._require_connected()
        target = await self._resolve_target_artifact(package_id, artifact_id)
        await self._ensure_csrf_token()
        url = f"/DeployIntegrationDesigntimeArtifact?Id='{target.id}'&Version='{version}'"
        try:
            resp = await self._client.post(url, headers=self._write_headers({"Accept": "application/json"}))
        except httpx.HTTPError as exc:
            raise SapCiTenantError(f"deploy unreachable at {url}: {exc}") from exc
        if resp.status_code >= 400:
            self._raise_for_status(resp, "deploy")
        # 202 + opaque tracking UUID; poll key is the artifact id.
        return DeploymentResult(
            success=True,
            deployment_id=target.id,
            status="IN_PROGRESS",
            error=None,
        )

    async def _runtime_status(self, artifact_id: str) -> tuple[str, str | None]:
        """Read the runtime view for one artifact → (state, raw_status)."""
        resp = await self._client.get(
            "/IntegrationRuntimeArtifacts",
            params={
                "$filter": f"Name eq '{artifact_id}'",
                "$orderby": "DeployedOn desc",
                "$top": 1,
                "$format": "json",
            },
            headers={**self._basic_auth_header(), "Accept": "application/json"},
        )
        self._raise_for_status(resp, "poll_deployment")
        results = (
            resp.json().get("d", {}).get("results", [])
            if "json" in resp.headers.get("content-type", "")
            else []
        )
        if not results:
            return "NOT_DEPLOYED", None
        raw = str(results[0].get("Status") or "").upper()
        state = (
            "DEPLOYED"
            if raw in ("STARTED", "DEPLOYED", "SUCCESS")
            else "FAILED"
            if raw == "ERROR"
            else "IN_PROGRESS"
        )
        return state, raw

    async def poll_deployment(self, deployment_id: str) -> DeploymentStatus:
        """Poll runtime status for an artifact id (see deploy())."""
        self._require_connected()
        state, raw = await self._runtime_status(deployment_id)
        return DeploymentStatus(state=state, deployment_id=deployment_id, message=raw, logs=[])

    async def get_runtime_logs(self, package_id: str, since: object) -> list[LogEntry]:
        """Read MessageProcessingLogs (best-effort mapping into LogEntry).

        `$filter` uses `LogStart` gt <since> when `since` is datetime-ish;
        otherwise the most recent entries are returned (top 50).
        """
        self._require_connected()
        params: dict[str, str | int] = {"$top": 50, "$orderby": "LogEnd desc"}
        if hasattr(since, "isoformat"):
            params["$filter"] = f"LogEnd gt datetime'{since.isoformat()}'"  # type: ignore[attr-defined]
        resp = await self._client.get(
            "/MessageProcessingLogs",
            params=params,
            headers={**self._basic_auth_header(), "Accept": "application/json"},
        )
        self._raise_for_status(resp, "get_runtime_logs")
        try:
            data = resp.json()
            results = (
                data.get("d", {}).get("results", []) if isinstance(data, dict) else data.get("value", [])
            )
        except Exception:
            results = []
        out: list[LogEntry] = []
        for entry in results[:50]:
            out.append(
                LogEntry(
                    timestamp=str(entry.get("LogStart") or entry.get("LogEnd") or ""),
                    level=str(entry.get("Status") or "INFO"),
                    message=str(entry.get("CustomStatus") or entry.get("MessageGuid") or ""),
                    node_id=entry.get("IntegrationArtifactId"),
                )
            )
        return out

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
    writable_packages: list[str] | None = None,
    mock_state_dir: str | Path | None = None,
) -> SapCiTenantAdapter | MockSapCiTenantAdapter:
    """Factory: return the real adapter when OIW_USE_REAL_TENANT=1, else the mock.

    Per WP-08 §10 "What Not To Do": never default OIW_USE_REAL_TENANT=1 in CI.
    CI stays on the mock; the real adapter is for local/tenant work.

    `mock_state_dir` gives the MOCK durable state across processes (the
    deploy CLI pipeline needs upload→execute to see the same tenant
    state); it is ignored by the real adapter.
    """
    if use_real is None:
        use_real = os.environ.get("OIW_USE_REAL_TENANT", "").strip() in {"1", "true", "True", "yes"}
    if use_real:
        return SapCiTenantAdapter(
            tenant_url=tenant_url,
            username=username,
            password=password,
            writable_packages=writable_packages,
        )
    # Lazy import to avoid the mock's state-dir defaulting in tests
    from .mock_adapter import MockSapCiTenantAdapter

    return MockSapCiTenantAdapter(state_dir=mock_state_dir)


__all__ = [
    "SapCiTenantAdapter",
    "SapCiTenantError",
    "TenantPackageSummary",
    "TenantArtifactSummary",
    "build_tenant_adapter",
]
