"""Pydantic response models matching packages/api-spec/openapi.yaml."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Error(BaseModel):
    message: str
    code: str | None = None
    details: dict | None = None


class ProjectSummary(BaseModel):
    id: str
    name: str
    path: str
    created: str
    flow_count: int = 0
    test_count: int = 0


class FlowSummary(BaseModel):
    id: str
    name: str
    version: int
    node_count: int
    test_count: int
    labels: dict[str, str] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    passed: bool = True


class TestResult(BaseModel):
    flow_id: str
    test_name: str
    passed: bool
    duration_ms: int
    failures: list[str] = Field(default_factory=list)


class BuildResult(BaseModel):
    out_dir: str
    manifest_path: str
    digest: str
    compiler_version: str
    target_profile: str
    entry_count: int


class GitStatus(BaseModel):
    branch: str
    head_sha: str
    dirty: bool
    ahead: int
    last_build_digest: str | None = None
    last_build_target: str | None = None


class ArchiveEntry(BaseModel):
    name: str
    compressed_size: int
    uncompressed_size: int
    is_dir: bool


class ArchiveManifest(BaseModel):
    path: str
    entry_count: int
    compressed_size: int
    uncompressed_size: int
    compression_ratio: float
    digest: str
    warnings: list[str] = Field(default_factory=list)
    entries: list[ArchiveEntry] = Field(default_factory=list)


class HealthStatus(BaseModel):
    status: str = "ok"
    version: str
