"""Tests for environment profile loading and validation (WP-05 Task 1).

Covers:
  - Load profile with env-var substitution
  - Reject profile with inline secret values
  - Validate required fields (target, auth, deploymentPolicy)
  - Reject profile referencing unknown credentialRef (missing for oauth2)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from oiw.environments import (
    EnvironmentProfileError,
    list_profiles,
    load_profile,
    load_profile_file,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "order-to-s4"


@pytest.fixture()
def env_vars():
    """Set up env vars for profile substitution."""
    old = {}
    test_vars = {
        "DEV_TENANT_URL": "https://dev.sap.com",
        "DEV_TOKEN_URL": "https://dev.sap.com/oauth/token",
        "DEV_CLIENT_ID": "dev-client-123",
        "TEST_TENANT_URL": "https://test.sap.com",
        "TEST_TOKEN_URL": "https://test.sap.com/oauth/token",
        "TEST_CLIENT_ID": "test-client-456",
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


def test_load_profile_with_env_var_substitution(env_vars) -> None:
    """Load dev.yaml — ${DEV_TENANT_URL} etc. should be substituted."""
    profile = load_profile(EXAMPLE, "dev")
    assert profile.name == "dev"
    assert profile.target == "sap-cloud-integration-2026-07"
    assert profile.tenant_url == "https://dev.sap.com"
    assert profile.auth is not None
    assert profile.auth.method == "oauth2-client-credentials"
    assert profile.auth.token_url == "https://dev.sap.com/oauth/token"
    assert profile.auth.client_id == "dev-client-123"
    assert profile.auth.credential_ref == "sap-dev-api-client"
    assert "S4_BASE_URL" in profile.externalized_parameters
    assert profile.deployment_policy.requires_approval is False


def test_load_profile_test_with_approvers(env_vars) -> None:
    """test.yaml has approvers and requiresApproval=True."""
    profile = load_profile(EXAMPLE, "test")
    assert profile.name == "test"
    assert profile.deployment_policy.requires_approval is True
    assert "integration-lead" in profile.deployment_policy.approvers
    assert "qa-lead" in profile.deployment_policy.approvers
    assert profile.deployment_policy.approval_ttl_hours == 12


def test_reject_profile_with_inline_secret(tmp_path: Path) -> None:
    """A profile with an inline `clientSecret` value must be rejected."""
    profile_yaml = """
apiVersion: oiw.dev/v1alpha1
kind: EnvironmentProfile
metadata:
  name: dev
spec:
  target: sap-cloud-integration-2026-07
  auth:
    method: oauth2-client-credentials
    clientId: my-client
    clientSecret: super-secret-value
    credentialRef: sap-dev
  deploymentPolicy:
    requiresApproval: false
"""
    p = tmp_path / "environments" / "dev.yaml"
    p.parent.mkdir(parents=True)
    p.write_text(profile_yaml)
    with pytest.raises(EnvironmentProfileError, match="inline secret"):
        load_profile_file(p)


def test_reject_profile_missing_required_fields(tmp_path: Path) -> None:
    """A profile missing spec.target must be rejected."""
    profile_yaml = """
apiVersion: oiw.dev/v1alpha1
kind: EnvironmentProfile
metadata:
  name: dev
spec:
  auth:
    method: oauth2-client-credentials
    credentialRef: sap-dev
  deploymentPolicy:
    requiresApproval: false
"""
    p = tmp_path / "environments" / "dev.yaml"
    p.parent.mkdir(parents=True)
    p.write_text(profile_yaml)
    with pytest.raises(EnvironmentProfileError, match="target is required"):
        load_profile_file(p)


def test_reject_profile_missing_credential_ref(tmp_path: Path) -> None:
    """An oauth2 profile without credentialRef must be rejected."""
    profile_yaml = """
apiVersion: oiw.dev/v1alpha1
kind: EnvironmentProfile
metadata:
  name: dev
spec:
  target: sap-cloud-integration-2026-07
  auth:
    method: oauth2-client-credentials
    clientId: my-client
  deploymentPolicy:
    requiresApproval: false
"""
    p = tmp_path / "environments" / "dev.yaml"
    p.parent.mkdir(parents=True)
    p.write_text(profile_yaml)
    with pytest.raises(EnvironmentProfileError, match="credentialRef is required"):
        load_profile_file(p)


def test_reject_profile_with_unset_env_var(tmp_path: Path) -> None:
    """A profile referencing an unset env var must be rejected."""
    # Ensure the env var is not set
    var_name = "UNSET_TEST_VAR_XYZ"
    old = os.environ.pop(var_name, None)
    try:
        profile_yaml = f"""
apiVersion: oiw.dev/v1alpha1
kind: EnvironmentProfile
metadata:
  name: dev
spec:
  target: sap-cloud-integration-2026-07
  tenantUrl: ${{{var_name}}}
  auth:
    method: oauth2-client-credentials
    credentialRef: sap-dev
  deploymentPolicy:
    requiresApproval: false
"""
        p = tmp_path / "environments" / "dev.yaml"
        p.parent.mkdir(parents=True)
        p.write_text(profile_yaml)
        with pytest.raises(EnvironmentProfileError, match="not set"):
            load_profile_file(p)
    finally:
        if old is not None:
            os.environ[var_name] = old


def test_list_profiles(env_vars) -> None:
    """list_profiles returns dev, prod, test (alphabetical)."""
    names = list_profiles(EXAMPLE)
    assert "dev" in names
    assert "prod" in names
    assert "test" in names
    # Should be sorted
    assert names == sorted(names)


def test_profile_not_found() -> None:
    """Loading a non-existent profile raises a clear error."""
    with pytest.raises(EnvironmentProfileError, match="not found"):
        load_profile(EXAMPLE, "nonexistent")
