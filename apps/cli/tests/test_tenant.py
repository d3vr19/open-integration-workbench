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


def _write_transport(artifact_id="MyFlow", artifact_version="1.0.0", *, empty_package=False):
    """MockTransport serving the write-path endpoints (WP-08 PR-9).

    Routes:
      GET  /                                  → service doc (+ CSRF token when fetched)
      GET  /IntegrationPackages('{pkg}')/...  → artifact list (or empty)
      PUT  /IntegrationDesigntimeArtifacts(...)/$value → 204
      POST /IntegrationRuntimeArtifacts       → deployment accepted
      GET  /IntegrationRuntimeArtifacts('dep-1') → DEPLOYED
      GET  /MessageProcessingLogs             → two log entries
    """
    import httpx

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["csrf_request_header"] = request.headers.get("X-CSRF-Token")
        auth = request.headers.get("Authorization", "")
        assert auth.startswith("Basic "), "Basic auth header missing"

        if request.method == "GET" and request.url.path.rstrip("/") in ("/api/v1", ""):
            if request.headers.get("X-CSRF-Token") == "fetch":
                return httpx.Response(
                    200,
                    json={"d": {"EntitySets": []}},
                    headers={"x-csrf-token": "test-csrf-token"},
                )
            return httpx.Response(200, json={"d": {"EntitySets": ["IntegrationPackages"]}})

        if (
            request.method == "GET"
            and "IntegrationDesigntimeArtifacts" in str(request.url)
            and "$value" not in str(request.url)
        ):
            results = (
                []
                if empty_package
                else [
                    {
                        "Id": artifact_id,
                        "Name": artifact_id,
                        "Version": artifact_version,
                        "__metadata": {"media_src": "https://example.invalid/api/v1/x/$value"},
                    }
                ]
            )
            # Created artifacts join the package listing (version read-back)
            if "brand_new_flow" in seen.get("created_ids", []):
                results.append(
                    {
                        "Id": "brand_new_flow",
                        "Name": "Brand New Flow",
                        "Version": "1.0.0",
                        "__metadata": {"media_src": "https://example.invalid/api/v1/y/$value"},
                    }
                )
            return httpx.Response(200, json={"d": {"results": results}})

        if request.method == "PUT" and "IntegrationDesigntimeArtifacts(Id=" in str(request.url):
            import json as _json

            seen["upload_payload"] = _json.loads(request.content)
            seen["csrf_sent"] = request.headers.get("x-csrf-token")
            return httpx.Response(204)

        if (
            request.method == "POST"
            and request.url.path.rstrip("/").endswith("/IntegrationDesigntimeArtifacts")
        ):
            import json as _json

            seen["create_payload"] = _json.loads(request.content)
            seen["create_csrf_sent"] = request.headers.get("x-csrf-token")
            seen.setdefault("created_ids", []).append(seen["create_payload"]["Id"])
            return httpx.Response(201, json={"d": {"Id": "brand_new_flow", "Version": "1.0.0"}})

        if request.method == "POST" and request.url.path.endswith("/IntegrationRuntimeArtifacts"):
            seen["deploy_payload"] = request.content
            return httpx.Response(200, json={"d": {"Id": "dep-1", "Status": "IN_PROGRESS"}})

        if request.method == "POST" and "DeployIntegrationDesigntimeArtifact" in str(request.url):
            assert request.url.params.get("Id") == f"'{artifact_id}'"  # OData v1 quotes params
            return httpx.Response(202, text="fd04ed7d-149b-45ab-4497-b1b5b983bbeb")

        if request.method == "GET" and request.url.path.endswith("/IntegrationRuntimeArtifacts"):
            return httpx.Response(
                200,
                json={
                    "d": {
                        "results": [
                            {"Id": artifact_id, "Name": artifact_id, "Version": "1.0.0", "Status": "STARTED"}
                        ]
                    }
                },
                headers={"content-type": "application/json"},
            )

        if request.method == "GET" and "MessageProcessingLogs" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "d": {
                        "results": [
                            {
                                "LogStart": "2026-08-25T00:00:00",
                                "Status": "COMPLETED",
                                "MessageGuid": "m-1",
                                "IntegrationArtifactId": artifact_id,
                            },
                            {
                                "LogStart": "2026-08-24T00:00:00",
                                "Status": "FAILED",
                                "MessageGuid": "m-2",
                                "IntegrationArtifactId": artifact_id,
                            },
                        ]
                    }
                },
            )

        return httpx.Response(404, json={"error": {"message": {"value": f"unrouted: {request.url}"}}})

    transport = httpx.MockTransport(handler)
    return transport, seen


def _connected_real_adapter(profile, transport, **kwargs):
    import httpx

    adapter = _RealAdapter(
        tenant_url="https://example.invalid/api/v1",
        username="sb-user",
        password="secret",
        client=httpx.AsyncClient(transport=transport, base_url="https://example.invalid/api/v1"),
        **kwargs,
    )
    _run(adapter.connect(profile))
    return adapter


def test_write_ops_refused_without_allowlist(profile) -> None:
    """Empty allowlist ⇒ every write fails loudly with remediation text."""
    adapter = _RealAdapter(tenant_url="https://example.invalid", username="u", password="p")
    with pytest.raises(SapCiTenantError, match="no writable packages configured"):
        _run(adapter.upload_package("AdequareGST", b"data", "sha256:abc"))
    with pytest.raises(SapCiTenantError, match="no writable packages configured"):
        _run(adapter.deploy("AdequareGST", "1.0.0"))


def test_write_ops_refused_outside_allowlist(profile) -> None:
    """A package not on the allowlist is refused even when others are allowed."""
    adapter = _RealAdapter(
        tenant_url="https://example.invalid", username="u", password="p", writable_packages=["AdequareGST"]
    )
    with pytest.raises(SapCiTenantError, match="not on the writable allowlist"):
        _run(adapter.upload_package("SomeProductionPackage", b"data", "sha256:abc"))


def test_upload_updates_existing_artifact(profile) -> None:
    """PUT $value carries real bytes + CSRF token into an EXISTING artifact."""
    transport, seen = _write_transport()
    adapter = _connected_real_adapter(profile, transport, writable_packages=["AdequareGST"])

    import base64 as _b64

    raw = b"PK\x03\x04fakezipbytes"
    result = _run(adapter.upload_package("AdequareGST", raw, "sha256:deadbeef"))
    assert result.success is True
    payload = seen["upload_payload"]
    assert "Id='MyFlow'" in seen["url"]
    assert "ArtifactContent" in payload
    assert _b64.b64decode(payload["ArtifactContent"]) == raw
    assert seen["csrf_sent"] == "test-csrf-token"
    _run(adapter.disconnect())


def test_upload_rejects_empty_archive_locally(profile) -> None:
    """Empty/truncated archives never reach the network."""
    transport, seen = _write_transport()
    adapter = _connected_real_adapter(profile, transport, writable_packages=["AdequareGST"])

    result = _run(adapter.upload_package("AdequareGST", b"", "sha256:e3b0"))
    assert result.success is False
    assert "empty or truncated" in (result.error or "")
    assert "upload_body" not in seen  # no PUT happened
    _run(adapter.disconnect())


def test_upload_refused_when_package_has_no_artifacts(profile) -> None:
    """Update-only policy: an EMPTY package cannot receive content."""
    transport, _seen = _write_transport(empty_package=True)
    adapter = _connected_real_adapter(profile, transport, writable_packages=["AdequareGST"])

    with pytest.raises(SapCiTenantError, match="update-only"):
        _run(adapter.upload_package("AdequareGST", b"PK\x03\x04zip", "sha256:aa"))
    _run(adapter.disconnect())


def test_create_artifact_posts_entity_with_full_payload(profile) -> None:
    """P6 create verb: POST /IntegrationDesigntimeArtifacts with Id/Version/
    PackageId/Name/ArtifactContent + CSRF token (edmx-proven shape)."""
    transport, seen = _write_transport()
    adapter = _connected_real_adapter(profile, transport, writable_packages=["AdequareGST"])

    import base64 as _b64

    raw = b"PK\x03\x04newbundle"
    result = _run(
        adapter.create_artifact("AdequareGST", "brand_new_flow", "Brand New Flow", raw)
    )
    assert result.success is True
    assert result.version == "1.0.0"  # read back from the artifact listing
    payload = seen.get("create_payload")
    assert payload is not None, "POST entity never reached the transport"
    assert payload["Id"] == "brand_new_flow"
    # LIVE FINDING (2026-09-02): Version must NOT be in the create payload —
    # the tenant auto-generates it ("must not be part of input payload").
    assert "Version" not in payload
    assert payload["PackageId"] == "AdequareGST"
    assert payload["Name"] == "Brand New Flow"
    assert _b64.b64decode(payload["ArtifactContent"]) == raw
    assert seen["create_csrf_sent"] == "test-csrf-token"
    _run(adapter.disconnect())


def test_create_artifact_refuses_existing_id_locally(profile) -> None:
    """Id-collision preflight: an existing artifact id never reaches POST
    (the tenant's 500 for POST-on-existing is misleading — refuse first)."""
    transport, seen = _write_transport()  # package already lists MyFlow
    adapter = _connected_real_adapter(profile, transport, writable_packages=["AdequareGST"])

    result = _run(adapter.create_artifact("AdequareGST", "MyFlow", "MyFlow", b"PK\x03\x04zip"))
    assert result.success is False
    assert "already exists" in (result.error or "")
    assert "create_payload" not in seen
    _run(adapter.disconnect())


def test_create_artifact_refused_outside_allowlist(profile) -> None:
    """Same policy gates as every write: allowlist refusal BEFORE network."""
    adapter = _RealAdapter(
        tenant_url="https://example.invalid", username="u", password="p",
        writable_packages=["AdequareGST"],
    )
    with pytest.raises(SapCiTenantError, match="not on the writable allowlist"):
        _run(adapter.create_artifact("OtherPackage", "x", "x", b"PK\x03\x04zip"))


def test_deploy_triggers_function_import_and_poll_maps_status(profile) -> None:
    """deploy() hits the function import with query params; poll reads the runtime view."""
    transport, seen = _write_transport()
    adapter = _connected_real_adapter(profile, transport, writable_packages=["AdequareGST"])

    result = _run(adapter.deploy("AdequareGST", "1.0.0"))
    assert result.success is True
    assert result.status == "IN_PROGRESS"
    assert "DeployIntegrationDesigntimeArtifact" in seen["url"]
    assert seen["url"].split("?")[1].startswith("Id='MyFlow'&Version=")

    status = _run(adapter.poll_deployment(result.deployment_id))
    assert status.state == "DEPLOYED"  # STARTED mapped to DEPLOYED
    assert status.message == "STARTED"
    _run(adapter.disconnect())


def test_get_runtime_logs_parses_message_processing_logs(profile) -> None:
    """get_runtime_logs() maps MPL entries into LogEntry records."""
    from datetime import datetime as _dt

    transport, _seen = _write_transport()
    adapter = _connected_real_adapter(profile, transport)

    logs = _run(adapter.get_runtime_logs("AdequareGST", since=_dt(2026, 8, 1)))
    assert len(logs) == 2
    assert logs[0].level == "COMPLETED"
    assert logs[1].level == "FAILED"
    _run(adapter.disconnect())


def test_writable_packages_resolved_from_env(profile, monkeypatch) -> None:
    """OIW_TENANT_WRITABLE_PACKAGES feeds the allowlist at connect()."""
    import httpx

    monkeypatch.setenv("OIW_TENANT_WRITABLE_PACKAGES", "ScratchA, ScratchB")
    transport, _seen = _write_transport()
    adapter = _RealAdapter(
        tenant_url="https://example.invalid/api/v1",
        username="u",
        password="p",
        client=httpx.AsyncClient(transport=transport, base_url="https://example.invalid/api/v1"),
    )
    assert adapter.writable_packages == []
    _run(adapter.connect(profile))
    assert adapter.writable_packages == ["ScratchA", "ScratchB"]
    _run(adapter.disconnect())


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


def test_artifact_pin_targets_only_the_pinned_artifact(profile) -> None:
    """PackageId/ArtifactId allowlist pins the update target (PR-9 safety)."""
    transport, seen = _write_transport(artifact_id="open_mateo_test")
    adapter = _connected_real_adapter(profile, transport, writable_packages=["AdaequareGST/open_mateo_test"])
    assert adapter._pinned_artifact("AdaequareGST") == "open_mateo_test"

    result = _run(adapter.upload_package("AdaequareGST", b"PK\x03\x04zip", "sha256:bb"))
    assert result.success is True
    # The POST targeted the PINNED artifact, not the first in the package
    assert "Id='open_mateo_test'" in seen["url"]
    _run(adapter.disconnect())


def test_artifact_pin_refuses_when_pinned_artifact_missing(profile) -> None:
    """A missing pinned artifact is an error — never fall back to a sibling."""
    transport, _seen = _write_transport()
    adapter = _connected_real_adapter(profile, transport, writable_packages=["AdaequareGST/does-not-exist"])
    with pytest.raises(SapCiTenantError, match="pinned artifact 'does-not-exist' not found"):
        _run(adapter.upload_package("AdaequareGST", b"PK\x03\x04zip", "sha256:cc"))
    _run(adapter.disconnect())


def test_unpinned_writable_package_still_refuses_nothing_new(profile) -> None:
    """A bare PackageId entry allows the first artifact (documented default)."""
    transport, seen = _write_transport()
    adapter = _connected_real_adapter(profile, transport, writable_packages=["AdaequareGST"])
    assert adapter._pinned_artifact("AdaequareGST") is None
    result = _run(adapter.upload_package("AdaequareGST", b"PK\x03\x04zip", "sha256:dd"))
    assert result.success is True
    assert "Id='MyFlow'" in seen["url"]  # top-of-list artifact
    _run(adapter.disconnect())


def test_create_artifact_probe_fallback_on_nav_wedge(monkeypatch, tmp_path):
    """Nav-wedge era (2026-09-03): when the package listing 404s (gateway
    cooldown), create_artifact probes the artifact KEY directly instead of
    dying — the artifact-key namespace stays healthy during cooldowns."""
    import asyncio

    import httpx

    from oiw.tenant.sap_ci_adapter import SapCiTenantAdapter

    calls = {"nav": 0, "probe": 0, "create": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "IntegrationPackages" in path and "IntegrationDesigntimeArtifacts" in path:
            calls["nav"] += 1
            return httpx.Response(404, json={"error": {"code": "Not Found"}})
        if "IntegrationDesigntimeArtifacts(Id=" in path and "$value" in path:
            calls["probe"] += 1
            return httpx.Response(404, json={"error": {"code": "Not Found"}})
        if path.endswith("/IntegrationDesigntimeArtifacts") and request.method == "POST":
            calls["create"] += 1
            return httpx.Response(201, json={"d": {"Id": "new-art"}})
        if request.method == "GET" and path.rstrip("/").endswith("/api/v1"):
            return httpx.Response(200, json={"d": {"EntitySets": []}}, headers={"x-csrf-token": "tok"})
        return httpx.Response(200, json={"d": {"results": []}})

    async def main():
        transport = httpx.MockTransport(handler)
        adapter = SapCiTenantAdapter(
            "https://t.example.com/api/v1", "u", "p",
            client=httpx.AsyncClient(transport=transport, base_url="https://t.example.com/api/v1"),
            writable_packages=["pkg/new-art"],
        )
        from oiw.environments import AuthConfig
        from oiw.environments import EnvironmentProfile as EnvProfile

        prof = EnvProfile(
            name="t", target="sap-cloud-integration-2026-07",
            tenant_url="https://t.example.com/api/v1",
            auth=AuthConfig(method="basic", credential_ref="x"),
        )
        await adapter.connect(prof)
        result = await adapter.create_artifact("pkg", "new-art", "New", b"ZIP-CONTENT-9876")
        await adapter.disconnect()
        return result

    result = asyncio.run(main())
    assert result.success, f"create must succeed via probe fallback: {result.error}"
    assert calls["nav"] == 2  # preflight + version read-back, both wedged
    assert calls["probe"] >= 2  # at least the preflight probes fired
    assert calls["create"] == 1


def test_create_artifact_refuses_existing_via_probe(monkeypatch):
    """If the probe finds the artifact alive (wedge-era listing), create
    refuses with the honest already-exists message (update path instead)."""
    import asyncio

    import httpx

    from oiw.tenant.sap_ci_adapter import SapCiTenantAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "IntegrationPackages" in path and "IntegrationDesigntimeArtifacts" in path:
            return httpx.Response(404, json={"error": {"code": "Not Found"}})
        if "IntegrationDesigntimeArtifacts(Id=" in path and "$value" in path:
            return httpx.Response(200, content=b"ZIP")  # exists!
        return httpx.Response(200, json={"d": {"results": []}})

    async def main():
        transport = httpx.MockTransport(handler)
        adapter = SapCiTenantAdapter(
            "https://t.example.com/api/v1", "u", "p",
            client=httpx.AsyncClient(transport=transport, base_url="https://t.example.com/api/v1"),
            writable_packages=["pkg/existing"],
        )
        from oiw.environments import AuthConfig
        from oiw.environments import EnvironmentProfile as EnvProfile

        prof = EnvProfile(
            name="t", target="sap-cloud-integration-2026-07",
            tenant_url="https://t.example.com/api/v1",
            auth=AuthConfig(method="basic", credential_ref="x"),
        )
        await adapter.connect(prof)
        result = await adapter.create_artifact("pkg", "existing", "X", b"ZIP-CONTENT-9876")
        await adapter.disconnect()
        return result

    result = asyncio.run(main())
    assert not result.success
    assert "already exists" in (result.error or "")
