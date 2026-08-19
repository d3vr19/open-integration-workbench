"""Tests for the tenant adapter interface + mock (WP-05 Task 2).

Covers:
  - Mock adapter: upload + deploy happy path
  - Mock adapter: upload invalid archive (rejects empty)
  - Mock adapter: deployment failure scenarios (auth, upload, deploy, timeout)
  - Mock adapter: poll deployment returns status transitions
  - Real adapter: raises NotImplementedError (OW-010 placeholder)
  - Profile loading with env var substitution
  - Connection with invalid credentials (fail_auth scenario)
  - Disconnect cleanup
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from oiw.environments import EnvironmentProfile, load_profile
from oiw.tenant import (
    MockSapCiTenantAdapter,
    MockTenantError,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "order-to-s4"


@pytest.fixture()
def env_vars():
    old = {}
    test_vars = {
        "DEV_TENANT_URL": "https://dev.sap.com",
        "DEV_TOKEN_URL": "https://dev.sap.com/oauth/token",
        "DEV_CLIENT_ID": "dev-client-123",
    }
    for k, v in test_vars.items():
        old[k] = os.environ.get(k)
        os.environ[k] = v
    yield
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture()
def profile(env_vars) -> EnvironmentProfile:
    return load_profile(EXAMPLE, "dev")


@pytest.fixture()
def mock_adapter(tmp_path: Path) -> MockSapCiTenantAdapter:
    return MockSapCiTenantAdapter(state_dir=tmp_path / "mock-tenant")


def _run(coro):
    """Run an async coroutine synchronously for tests."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_mock_upload_deploy_happy_path(mock_adapter, profile) -> None:
    """Upload + deploy + poll happy path."""
    _run(mock_adapter.connect(profile))
    assert mock_adapter.is_connected

    # Upload
    archive = b"fake-zip-content"
    upload = _run(mock_adapter.upload_package("order-to-s4", archive, "sha256:abc123"))
    assert upload.success
    assert upload.version is not None

    # Deploy
    deploy = _run(mock_adapter.deploy("order-to-s4", upload.version))
    assert deploy.success
    assert deploy.status == "DEPLOYED"
    assert deploy.deployment_id is not None

    # Poll
    status = _run(mock_adapter.poll_deployment(deploy.deployment_id))
    assert status.state == "DEPLOYED"

    # Verify digest is stored
    digest = _run(mock_adapter.get_artifact_digest("order-to-s4"))
    assert digest == "sha256:abc123"

    _run(mock_adapter.disconnect())


def test_mock_upload_rejects_empty_archive(mock_adapter, profile) -> None:
    """Empty archive bytes are rejected."""
    _run(mock_adapter.connect(profile))
    result = _run(mock_adapter.upload_package("pkg", b"", "sha256:abc"))
    assert not result.success
    assert "empty" in result.error
    _run(mock_adapter.disconnect())


# ---------------------------------------------------------------------------
# Failure scenarios
# ---------------------------------------------------------------------------


def test_mock_fail_auth(profile, tmp_path: Path) -> None:
    """fail_auth scenario: connect() raises MockTenantError."""
    adapter = MockSapCiTenantAdapter(state_dir=tmp_path / "mock", failure_scenario="fail_auth")
    with pytest.raises(MockTenantError, match="authentication failed"):
        _run(adapter.connect(profile))


def test_mock_fail_upload(mock_adapter, profile) -> None:
    """fail_upload scenario: upload_package returns failure."""
    adapter = MockSapCiTenantAdapter(failure_scenario="fail_upload")
    _run(adapter.connect(profile))
    result = _run(adapter.upload_package("pkg", b"data", "sha256:abc"))
    assert not result.success
    assert "upload failed" in result.error


def test_mock_fail_deploy(mock_adapter, profile) -> None:
    """fail_deploy scenario: deploy() returns FAILED."""
    adapter = MockSapCiTenantAdapter(failure_scenario="fail_deploy")
    _run(adapter.connect(profile))
    result = _run(adapter.deploy("pkg", "v1"))
    assert not result.success
    assert result.status == "FAILED"


def test_mock_deploy_timeout(profile) -> None:
    """deploy_timeout scenario: deploy stays IN_PROGRESS."""
    adapter = MockSapCiTenantAdapter(failure_scenario="deploy_timeout", deploy_latency_seconds=0.01)
    _run(adapter.connect(profile))
    result = _run(adapter.deploy("pkg", "v1"))
    assert result.success
    assert result.status == "IN_PROGRESS"
    # Poll — should still be IN_PROGRESS
    status = _run(adapter.poll_deployment(result.deployment_id))
    assert status.state == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# Poll + state
# ---------------------------------------------------------------------------


def test_mock_poll_unknown_deployment(mock_adapter, profile) -> None:
    """Polling an unknown deployment_id returns FAILED."""
    _run(mock_adapter.connect(profile))
    status = _run(mock_adapter.poll_deployment("nonexistent"))
    assert status.state == "FAILED"


def test_mock_get_artifact_version_none_when_not_deployed(mock_adapter, profile) -> None:
    """get_artifact_version returns None when package was never uploaded."""
    _run(mock_adapter.connect(profile))
    version = _run(mock_adapter.get_artifact_version("never-uploaded"))
    assert version is None


# ---------------------------------------------------------------------------
# Real adapter (WP-08 Track 0): GET-only against the live OData API
# ---------------------------------------------------------------------------

from oiw.tenant import SapCiTenantError, build_tenant_adapter  # noqa: E402
from oiw.tenant.sap_ci_adapter import SapCiTenantAdapter as _RealAdapter  # noqa: E402


def _mock_transport(handler):
    import httpx

    return httpx.MockTransport(handler)


def test_real_adapter_rejects_when_credentials_missing(profile) -> None:
    """connect() raises SapCiTenantError when no credentials are configured."""
    adapter = _RealAdapter(tenant_url="https://example.invalid", username="", password="")
    with pytest.raises(SapCiTenantError, match="credentials not configured"):
        _run(adapter.connect(profile))


def test_real_adapter_connect_validates_credentials(profile) -> None:
    """connect() validates Basic auth by hitting the service root."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        # Verify Basic auth header is present
        auth = request.headers.get("Authorization", "")
        assert auth.startswith("Basic "), "Basic auth header missing"
        # Return a small service document
        return httpx.Response(200, json={"d": {"EntitySets": ["IntegrationPackages"]}})

    adapter = _RealAdapter(
        tenant_url="https://example.invalid/api/v1",
        username="sb-user",
        password="secret",
        client=httpx.AsyncClient(
            transport=_mock_transport(handler), base_url="https://example.invalid/api/v1"
        ),
    )
    _run(adapter.connect(profile))
    assert adapter.is_connected
    _run(adapter.disconnect())


def test_real_adapter_connect_raises_on_401(profile) -> None:
    """connect() raises SapCiTenantError on HTTP 401 (bad credentials)."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Unauthorized"}})

    adapter = _RealAdapter(
        tenant_url="https://example.invalid/api/v1",
        username="bad",
        password="creds",
        client=httpx.AsyncClient(
            transport=_mock_transport(handler), base_url="https://example.invalid/api/v1"
        ),
    )
    with pytest.raises(SapCiTenantError, match="HTTP 401"):
        _run(adapter.connect(profile))


def test_real_adapter_list_packages_parses_odata(profile) -> None:
    """list_packages() correctly parses SAP CI's `d.results` OData format."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        # Service root for connect()
        if url.rstrip("/") in {"https://example.invalid/api/v1", "https://example.invalid/api/v1/"}:
            return httpx.Response(200, json={"d": {"EntitySets": ["IntegrationPackages"]}})
        assert "/IntegrationPackages" in url, f"unexpected URL: {url}"
        return httpx.Response(
            200,
            json={
                "d": {
                    "results": [
                        {
                            "Id": "PkgA",
                            "Name": "Package A",
                            "Version": "1.0.0",
                            "Mode": "EDIT_ALLOWED",
                            "ModifiedBy": "alice@example.com",
                            "ResourceId": "abc123",
                        }
                    ]
                }
            },
        )

    adapter = _RealAdapter(
        tenant_url="https://example.invalid/api/v1",
        username="u",
        password="p",
        client=httpx.AsyncClient(
            transport=_mock_transport(handler), base_url="https://example.invalid/api/v1"
        ),
    )
    _run(adapter.connect(profile))
    pkgs = _run(adapter.list_packages(top=10))
    assert len(pkgs) == 1
    assert pkgs[0].id == "PkgA"
    assert pkgs[0].name == "Package A"
    assert pkgs[0].mode == "EDIT_ALLOWED"
    _run(adapter.disconnect())


def test_real_adapter_download_artifact_returns_zip_bytes(profile) -> None:
    """download_artifact() returns the raw ZIP bytes from $value."""
    import httpx

    fake_zip = b"PK\x03\x04fake-zip-bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.rstrip("/") in {"https://example.invalid/api/v1", "https://example.invalid/api/v1/"}:
            return httpx.Response(200, json={"d": {"EntitySets": ["IntegrationPackages"]}})
        if "/$value" in url and "IntegrationDesigntimeArtifacts" in url:
            return httpx.Response(200, content=fake_zip, headers={"content-type": "application/zip"})
        return httpx.Response(404)

    adapter = _RealAdapter(
        tenant_url="https://example.invalid/api/v1",
        username="u",
        password="p",
        client=httpx.AsyncClient(
            transport=_mock_transport(handler), base_url="https://example.invalid/api/v1"
        ),
    )
    _run(adapter.connect(profile))
    blob = _run(adapter.download_artifact("MyFlow", "1.0.0"))
    assert blob == fake_zip
    _run(adapter.disconnect())


def test_real_adapter_write_ops_not_implemented(profile) -> None:
    """upload_package / deploy / poll_deployment remain NotImplementedError (WP-08 §C-004)."""
    adapter = _RealAdapter(tenant_url="https://example.invalid", username="u", password="p")
    with pytest.raises(NotImplementedError, match="WP-08"):
        _run(adapter.upload_package("pkg", b"data", "sha256:abc"))
    with pytest.raises(NotImplementedError, match="WP-08"):
        _run(adapter.deploy("pkg", "1.0.0"))
    with pytest.raises(NotImplementedError, match="no deploy path"):
        _run(adapter.poll_deployment("dep-1"))


def test_build_tenant_adapter_returns_mock_by_default() -> None:
    """build_tenant_adapter() returns Mock when OIW_USE_REAL_TENANT is unset."""
    adapter = build_tenant_adapter(use_real=False)
    from oiw.tenant.mock_adapter import MockSapCiTenantAdapter

    assert isinstance(adapter, MockSapCiTenantAdapter)


def test_build_tenant_adapter_returns_real_when_opted_in() -> None:
    """build_tenant_adapter(use_real=True) returns SapCiTenantAdapter."""
    adapter = build_tenant_adapter(use_real=True, tenant_url="https://x", username="u", password="p")
    assert isinstance(adapter, _RealAdapter)


# ---------------------------------------------------------------------------
# Disconnect cleanup
# ---------------------------------------------------------------------------


def test_disconnect_clears_connection(mock_adapter, profile) -> None:
    """After disconnect, is_connected is False."""
    _run(mock_adapter.connect(profile))
    assert mock_adapter.is_connected
    _run(mock_adapter.disconnect())
    assert not mock_adapter.is_connected


def test_state_persisted_across_reconnect(mock_adapter, profile, tmp_path: Path) -> None:
    """State persists: upload, disconnect, reconnect, verify digest still there."""
    _run(mock_adapter.connect(profile))
    _run(mock_adapter.upload_package("pkg", b"data", "sha256:persist"))
    _run(mock_adapter.disconnect())

    # Reconnect with a new adapter instance using the same state dir
    adapter2 = MockSapCiTenantAdapter(state_dir=tmp_path / "mock-tenant")
    _run(adapter2.connect(profile))
    digest = _run(adapter2.get_artifact_digest("pkg"))
    assert digest == "sha256:persist"
    _run(adapter2.disconnect())


def test_runtime_logs_empty(mock_adapter, profile) -> None:
    """Mock tenant returns empty runtime logs."""
    _run(mock_adapter.connect(profile))
    logs = _run(mock_adapter.get_runtime_logs("pkg", datetime.now(tz=UTC)))
    assert logs == []
