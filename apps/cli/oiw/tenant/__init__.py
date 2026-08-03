"""Tenant adapter package (WP-05 Task 2).

Spec ref: §18 (Tenant Connectivity).

A TenantAdapter is the abstraction over a specific tenant's deployment
API (SAP CI, or a mock for testing). The MVP implementation is a mock
adapter; the real SAP CI adapter is gated on OW-010 (tenant access).
"""

from __future__ import annotations

from .adapter import (
    ArtifactVersion,
    DeploymentResult,
    DeploymentStatus,
    LogEntry,
    TenantAdapter,
    UploadResult,
)
from .mock_adapter import MockSapCiTenantAdapter, MockTenantError
from .sap_ci_adapter import SapCiTenantAdapter

__all__ = [
    "TenantAdapter",
    "ArtifactVersion",
    "DeploymentResult",
    "DeploymentStatus",
    "LogEntry",
    "UploadResult",
    "MockSapCiTenantAdapter",
    "MockTenantError",
    "SapCiTenantAdapter",
]
