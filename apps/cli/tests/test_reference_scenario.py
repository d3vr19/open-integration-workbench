"""End-to-end tests for the reference scenario (spec §26.3)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from oiw.compiler.export import BuildError, build_artifact
from oiw.project import Project
from oiw.schema_validator import validate_project
from oiw.testing import run_tests

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "order-to-s4"


@pytest.fixture(scope="module")
def project() -> Project:
    return Project.load(EXAMPLE)


def test_project_loads(project: Project) -> None:
    assert project.id == "customer-order-integration"
    assert len(project.flows) == 1
    assert project.flows[0].id == "order-to-s4"
    assert len(project.tests) == 2


def test_schema_validation_passes(project: Project) -> None:
    result = validate_project(project)
    assert result.errors == [], f"schema errors: {result.errors}"


def test_all_tests_pass(project: Project) -> None:
    results = run_tests(project)
    assert len(results) == 2, f"expected 2 tests, got {len(results)}"
    for r in results:
        assert r.passed, f"{r.flow_id}::{r.test_name} failed: {r.failures}"


def test_build_produces_deterministic_artifact(project: Project, tmp_path: Path) -> None:
    out1 = tmp_path / "build1"
    out2 = tmp_path / "build2"
    r1 = build_artifact(project, "sap-cloud-integration-2026-07", out1)
    r2 = build_artifact(project, "sap-cloud-integration-2026-07", out2)
    assert r1.digest == r2.digest, f"non-deterministic build:\n  first:  {r1.digest}\n  second: {r2.digest}"
    assert r1.digest.startswith("sha256:")
    assert len(r1.entries) > 0


def test_build_rejects_undeclared_target_profile(project: Project, tmp_path: Path) -> None:
    with pytest.raises(BuildError, match="not declared"):
        build_artifact(project, "undeclared-profile", tmp_path)


def test_cli_validate_command() -> None:
    """`oiw validate --strict --project <path>` exits 0 on the reference scenario."""
    result = subprocess.run(
        [sys.executable, "-m", "oiw.cli", "validate", "--strict", "--project", str(EXAMPLE)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"validate failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"


def test_cli_test_command() -> None:
    """`oiw test --all --project <path>` exits 0 on the reference scenario."""
    result = subprocess.run(
        [sys.executable, "-m", "oiw.cli", "test", "--all", "--project", str(EXAMPLE)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "2/2 passed" in result.stdout


def test_cli_build_command() -> None:
    """`oiw build --target <profile> --project <path>` exits 0 and produces a digest."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "oiw.cli",
            "build",
            "--target",
            "sap-cloud-integration-2026-07",
            "--project",
            str(EXAMPLE),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "sha256:" in result.stdout
