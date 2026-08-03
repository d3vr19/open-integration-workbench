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
    SapCiTenantAdapter,
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
    return asyncio.get_event_loop().run_until_complete(coro)


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
# Real adapter stub
# ---------------------------------------------------------------------------


def test_real_adapter_raises_not_implemented() -> None:
    """SapCiTenantAdapter raises NotImplementedError (OW-010 placeholder)."""
    adapter = SapCiTenantAdapter()
    with pytest.raises(NotImplementedError, match="OW-010"):
        _run(adapter.connect(profile))  # noqa: F821 — profile from fixture scope

    with pytest.raises(NotImplementedError, match="OW-010"):
        _run(adapter.upload_package("pkg", b"data", "sha256:abc"))


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
