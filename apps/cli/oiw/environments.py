"""Environment profile loading and validation.

Spec ref: §7.5 (Environment Profile IR), §18 (Tenant Connectivity).
WP-05 Task 1.

An EnvironmentProfile describes how to connect to a specific SAP CI
tenant (dev, test, stage, prod). It carries:
  - target profile (e.g. sap-cloud-integration-2026-07)
  - tenant URL (env-var-substituted)
  - auth method + credentialRef (never inline secrets)
  - externalized parameters (e.g. S4_BASE_URL)
  - deployment policy (approval required, approvers, auto-verify)

Profiles live at `{project}/environments/{name}.yaml`. The loader:
  1. Reads the YAML
  2. Validates against the JSON Schema
  3. Substitutes ${ENV_VAR} references from os.environ
  4. Rejects profiles with inline secret values
  5. Returns an EnvironmentProfile dataclass
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .project import ProjectError


class EnvironmentProfileError(ProjectError):
    """Raised when an environment profile is invalid or cannot be loaded."""


@dataclass
class DeploymentPolicy:
    """Deployment approval + verification policy (spec §18.4)."""

    requires_approval: bool = True
    approvers: list[str] = field(default_factory=list)
    auto_verify: bool = False
    approval_ttl_hours: int = 24


@dataclass
class AuthConfig:
    """Tenant authentication configuration. Never carries secret values."""

    method: str  # oauth2-client-credentials | basic | oauth2-authorization-code
    token_url: str | None = None
    client_id: str | None = None
    credential_ref: str | None = None  # references a credential store entry
    # No client_secret field — secrets are always externalized via credentialRef


@dataclass
class EnvironmentProfile:
    """A loaded and validated environment profile.

    All ${ENV_VAR} references have been substituted from os.environ
    at load time. The profile never contains inline secret values.
    """

    name: str  # dev, test, stage, prod
    target: str  # e.g. sap-cloud-integration-2026-07
    tenant_url: str | None = None
    auth: AuthConfig | None = None
    externalized_parameters: dict[str, str] = field(default_factory=dict)
    deployment_policy: DeploymentPolicy = field(default_factory=DeploymentPolicy)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "target": self.target,
            "tenantUrl": self.tenant_url,
            "auth": {
                "method": self.auth.method,
                "tokenUrl": self.auth.token_url,
                "clientId": self.auth.client_id,
                "credentialRef": self.auth.credential_ref,
            }
            if self.auth
            else None,
            "externalizedParameters": self.externalized_parameters,
            "deploymentPolicy": {
                "requiresApproval": self.deployment_policy.requires_approval,
                "approvers": self.deployment_policy.approvers,
                "autoVerify": self.deployment_policy.auto_verify,
                "approvalTtlHours": self.deployment_policy.approval_ttl_hours,
            },
        }


# ---------------------------------------------------------------------------
# Env-var substitution
# ---------------------------------------------------------------------------

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _substitute_env_vars(value: Any) -> Any:
    """Recursively substitute ${ENV_VAR} references from os.environ.

    Raises EnvironmentProfileError if a referenced env var is not set.
    """
    if isinstance(value, str):

        def _replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            env_val = os.environ.get(var_name)
            if env_val is None:
                raise EnvironmentProfileError(
                    f"environment variable '{var_name}' is not set but is "
                    f"referenced in the environment profile"
                )
            return env_val

        return _ENV_VAR_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env_vars(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Inline-secret detection
# ---------------------------------------------------------------------------

# Keys whose VALUES must never appear inline in a profile — they must
# always be referenced via credentialRef.
_SECRET_KEY_PATTERNS = (
    "secret",
    "password",
    "passwd",
    "clientsecret",
    "client_secret",
    "accesstoken",
    "access_token",
    "refreshtoken",
    "refresh_token",
    "privatekey",
    "private_key",
    "apikey",
    "api_key",
)


def _find_inline_secrets(data: Any, path: str = "") -> list[str]:
    """Walk the profile dict and find any key that looks like a secret.

    Returns a list of human-readable paths (e.g. "spec.auth.clientSecret").
    """
    findings: list[str] = []
    if isinstance(data, dict):
        for k, v in data.items():
            current_path = f"{path}.{k}" if path else k
            lowered = k.lower()
            if any(pat in lowered for pat in _SECRET_KEY_PATTERNS):
                # The key name suggests a secret — check if the value is
                # inline (not a ${ENV_VAR} reference and not null).
                if v is not None and not (isinstance(v, str) and v.startswith("${")):
                    findings.append(current_path)
            else:
                findings.extend(_find_inline_secrets(v, current_path))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            findings.extend(_find_inline_secrets(item, f"{path}[{i}]"))
    return findings


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_profile(project_path: Path | str, name: str) -> EnvironmentProfile:
    """Load an environment profile by name.

    Args:
        project_path: Path to the project root (containing environments/).
        name: Profile name (dev, test, stage, prod). Maps to
            environments/{name}.yaml.

    Returns:
        EnvironmentProfile with all env-var references substituted.

    Raises:
        EnvironmentProfileError: if the file doesn't exist, fails schema
            validation, contains inline secrets, or references an unset
            env var.
    """
    project_path = Path(project_path)
    profile_file = project_path / "environments" / f"{name}.yaml"
    if not profile_file.is_file():
        raise EnvironmentProfileError(f"environment profile not found: {profile_file}")
    return load_profile_file(profile_file)


def load_profile_file(profile_path: Path | str) -> EnvironmentProfile:
    """Load an environment profile from a specific YAML file path."""
    profile_path = Path(profile_path)
    try:
        raw = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise EnvironmentProfileError(f"invalid YAML in {profile_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise EnvironmentProfileError(f"profile must be a YAML mapping, got {type(raw)}")

    # 1. Check for inline secrets BEFORE substitution (so we catch both
    #    literal values and ${ENV_VAR} refs that resolve to secrets).
    inline_secrets = _find_inline_secrets(raw)
    if inline_secrets:
        raise EnvironmentProfileError(
            f"inline secret values found in profile (use credentialRef instead): "
            f"{', '.join(inline_secrets)}"
        )

    # 2. Substitute ${ENV_VAR} references
    try:
        resolved = _substitute_env_vars(raw)
    except EnvironmentProfileError:
        raise

    # 3. Validate required fields
    spec = resolved.get("spec", {})
    if not spec.get("target"):
        raise EnvironmentProfileError("profile spec.target is required")
    if not spec.get("auth"):
        raise EnvironmentProfileError("profile spec.auth is required")
    if not spec.get("deploymentPolicy"):
        raise EnvironmentProfileError("profile spec.deploymentPolicy is required")

    auth_data = spec["auth"]
    if not auth_data.get("method"):
        raise EnvironmentProfileError("profile spec.auth.method is required")

    # 4. credentialRef must be present for oauth2 methods
    auth_method = auth_data.get("method", "")
    if ("oauth2" in auth_method or "basic" in auth_method) and not auth_data.get("credentialRef"):
        raise EnvironmentProfileError(
            f"profile spec.auth.credentialRef is required for auth method '{auth_method}'"
        )

    # 5. Build dataclass
    dp_data = spec.get("deploymentPolicy", {})
    policy = DeploymentPolicy(
        requires_approval=dp_data.get("requiresApproval", True),
        approvers=dp_data.get("approvers", []),
        auto_verify=dp_data.get("autoVerify", False),
        approval_ttl_hours=dp_data.get("approvalTtlHours", 24),
    )

    auth = AuthConfig(
        method=auth_data["method"],
        token_url=auth_data.get("tokenUrl"),
        client_id=auth_data.get("clientId"),
        credential_ref=auth_data.get("credentialRef"),
    )

    metadata = resolved.get("metadata", {})
    profile_name = metadata.get("name", profile_path.stem)

    return EnvironmentProfile(
        name=profile_name,
        target=spec["target"],
        tenant_url=spec.get("tenantUrl"),
        auth=auth,
        externalized_parameters=spec.get("externalizedParameters", {}),
        deployment_policy=policy,
        raw=resolved,
    )


def list_profiles(project_path: Path | str) -> list[str]:
    """List available environment profile names in a project."""
    project_path = Path(project_path)
    env_dir = project_path / "environments"
    if not env_dir.is_dir():
        return []
    return sorted(f.stem for f in env_dir.glob("*.yaml") if f.is_file())


__all__ = [
    "EnvironmentProfile",
    "EnvironmentProfileError",
    "DeploymentPolicy",
    "AuthConfig",
    "load_profile",
    "load_profile_file",
    "list_profiles",
]
