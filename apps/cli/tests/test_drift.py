"""Tests for drift detection (WP-05 Task 4).

Covers:
  - No tenant artifact → safe to upload
  - Digests match → safe to upload
  - Digests differ → drift detected, upload blocked
  - Drift report includes recommendation and evidence
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from oiw.deploy import DriftDetector, DriftReport
from oiw.environments import load_profile
from oiw.tenant import MockSapCiTenantAdapter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "order-to-s4"


@pytest.fixture()
def env_vars():
    old = {}
    for k in ("DEV_TENANT_URL", "DEV_TOKEN_URL", "DEV_CLIENT_ID"):
        old[k] = os.environ.get(k)
        os.environ[k] = f"https://{k.lower()}.example.com"
    yield
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture()
def adapter(tmp_path: Path, env_vars) -> MockSapCiTenantAdapter:
    a = MockSapCiTenantAdapter(state_dir=tmp_path / "mock")
    profile = load_profile(EXAMPLE, "dev")
    asyncio.get_event_loop().run_until_complete(a.connect(profile))
    return a


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_no_tenant_artifact_safe_to_upload(adapter: MockSapCiTenantAdapter) -> None:
    """No artifact on tenant → NO_TENANT_ARTIFACT, safe to upload."""
    detector = DriftDetector()
    report = _run(detector.detect_drift("sha256:local", adapter, "never-uploaded"))
    assert report.status == "NO_TENANT_ARTIFACT"
    assert report.safe_to_upload is True
    assert report.tenant_digest is None


def test_digests_match_safe_to_upload(adapter: MockSapCiTenantAdapter) -> None:
    """Local and tenant digests match → IN_SYNC, safe to upload."""
    _run(adapter.upload_package("pkg", b"data", "sha256:abc123"))
    detector = DriftDetector()
    report = _run(detector.detect_drift("sha256:abc123", adapter, "pkg"))
    assert report.status == "IN_SYNC"
    assert report.safe_to_upload is True
    assert report.local_digest == "sha256:abc123"
    assert report.tenant_digest == "sha256:abc123"


def test_digests_differ_drift_detected(adapter: MockSapCiTenantAdapter) -> None:
    """Local and tenant digests differ → DRIFT_DETECTED, upload blocked."""
    _run(adapter.upload_package("pkg", b"data", "sha256:tenant-version"))
    detector = DriftDetector()
    report = _run(detector.detect_drift("sha256:local-version", adapter, "pkg"))
    assert report.status == "DRIFT_DETECTED"
    assert report.safe_to_upload is False
    assert report.local_digest == "sha256:local-version"
    assert report.tenant_digest == "sha256:tenant-version"


def test_drift_report_includes_recommendation(adapter: MockSapCiTenantAdapter) -> None:
    """Drift report includes a human-readable recommendation."""
    _run(adapter.upload_package("pkg", b"data", "sha256:tenant"))
    detector = DriftDetector()
    report = _run(detector.detect_drift("sha256:local", adapter, "pkg"))
    assert "blocked" in report.recommendation.lower() or "resolve" in report.recommendation.lower()
    assert report.tenant_version is not None


def test_drift_report_to_dict(adapter: MockSapCiTenantAdapter) -> None:
    """DriftReport.to_dict() produces a JSON-serializable dict."""
    report = DriftReport(
        status="IN_SYNC",
        safe_to_upload=True,
        local_digest="sha256:abc",
        tenant_digest="sha256:abc",
    )
    d = report.to_dict()
    assert d["status"] == "IN_SYNC"
    assert d["safeToUpload"] is True
    assert d["localDigest"] == "sha256:abc"
