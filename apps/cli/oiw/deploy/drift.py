"""Drift detection (WP-05 Task 4).

Spec ref: §18.6 (Drift Detection).

Drift detection compares the local build digest against the digest of
the artifact currently deployed on the tenant. If they differ, it means
someone modified the tenant directly (outside the OIW pipeline) —
uploading would silently overwrite their changes.

The DriftDetector returns a DriftReport with:
  - status: IN_SYNC | NO_TENANT_ARTIFACT | DRIFT_DETECTED
  - safe_to_upload: True only if IN_SYNC or NO_TENANT_ARTIFACT
  - local_digest, tenant_digest, tenant_version (for diagnostics)
  - recommendation (human-readable next step)

The deployment pipeline calls this before every upload; if
safe_to_upload is False, the upload is blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tenant.adapter import TenantAdapter


@dataclass
class DriftReport:
    """Result of a drift detection check.

    Attributes:
        status: IN_SYNC | NO_TENANT_ARTIFACT | DRIFT_DETECTED
        safe_to_upload: True if the upload should proceed
        local_digest: the local build's SHA-256 digest
        tenant_digest: the tenant's currently deployed digest (None if no artifact)
        tenant_version: the tenant's currently deployed version (None if no artifact)
        recommendation: human-readable next step
    """

    status: str  # IN_SYNC | NO_TENANT_ARTIFACT | DRIFT_DETECTED
    safe_to_upload: bool
    local_digest: str | None = None
    tenant_digest: str | None = None
    tenant_version: str | None = None
    recommendation: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "safeToUpload": self.safe_to_upload,
            "localDigest": self.local_digest,
            "tenantDigest": self.tenant_digest,
            "tenantVersion": self.tenant_version,
            "recommendation": self.recommendation,
        }


class DriftDetector:
    """Compares local build digest against tenant state.

    Usage:
        detector = DriftDetector()
        report = await detector.detect_drift(
            local_build_digest="sha256:abc123",
            tenant_adapter=adapter,
            package_id="order-to-s4",
        )
        if not report.safe_to_upload:
            print(f"Upload blocked: {report.status}")
            print(report.recommendation)
    """

    async def detect_drift(
        self,
        local_build_digest: str,
        tenant_adapter: TenantAdapter,
        package_id: str,
    ) -> DriftReport:
        """Compare local build against tenant state.

        Args:
            local_build_digest: SHA-256 digest of the local build artifact.
            tenant_adapter: connected TenantAdapter.
            package_id: the package ID to check on the tenant.

        Returns:
            DriftReport with status + safe_to_upload flag.
        """
        tenant_version_info = await tenant_adapter.get_artifact_version(package_id)
        tenant_digest = await tenant_adapter.get_artifact_digest(package_id)

        if tenant_digest is None:
            return DriftReport(
                status="NO_TENANT_ARTIFACT",
                safe_to_upload=True,
                local_digest=local_build_digest,
                tenant_digest=None,
                tenant_version=None,
                recommendation="No artifact on tenant. Safe to upload.",
            )

        if tenant_digest == local_build_digest:
            return DriftReport(
                status="IN_SYNC",
                safe_to_upload=True,
                local_digest=local_build_digest,
                tenant_digest=tenant_digest,
                tenant_version=tenant_version_info.version if tenant_version_info else None,
                recommendation="Local build matches tenant. Safe to upload.",
            )

        # Digests differ — drift detected
        return DriftReport(
            status="DRIFT_DETECTED",
            safe_to_upload=False,
            local_digest=local_build_digest,
            tenant_digest=tenant_digest,
            tenant_version=tenant_version_info.version if tenant_version_info else None,
            recommendation=(
                "Tenant has been modified since last export. Upload blocked. "
                "Fetch the tenant artifact, review changes, resolve manually."
            ),
        )


__all__ = ["DriftDetector", "DriftReport"]
