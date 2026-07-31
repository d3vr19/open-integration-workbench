"""Tests for the rule-based validators (spec §14.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from oiw.project import Project
from oiw.validators.rules import run_rule_validators

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "order-to-s4"


@pytest.fixture(scope="module")
def project() -> Project:
    return Project.load(EXAMPLE)


def test_reference_scenario_has_no_errors(project: Project) -> None:
    errors, warnings = run_rule_validators(project)
    assert errors == [], f"unexpected errors: {errors}"
    # The reference scenario declares error handling, so OIW-W002 should NOT fire.
    assert not any("OIW-W002" in w for w in warnings), f"OIW-W002 should not fire: {warnings}"


def test_oiw_e002_inline_secret_detected(tmp_path: Path) -> None:
    """A flow with an inline secret in node config triggers OIW-E002."""
    project_dir = tmp_path / "secret-test"
    project_dir.mkdir()
    (project_dir / "oiw.yaml").write_text(
        """apiVersion: oiw.dev/v1alpha1
kind: IntegrationProject
metadata:
  id: secret-test
  name: Secret Test
  created: "1970-01-01T00:00:00Z"
spec:
  package: package/package.yaml
  targetProfiles: [sap-cloud-integration-2026-07]
  minimumCompilerVersion: 0.1.0
"""
    )
    (project_dir / "flows" / "x").mkdir(parents=True)
    (project_dir / "flows" / "x" / "flow.yaml").write_text(
        """apiVersion: oiw.dev/v1alpha1
kind: IntegrationFlow
metadata:
  id: x
  name: x
  version: 1
spec:
  entrypoints:
    - id: sender-http
      type: sender.http
      config:
        path: /x
        methods: [POST]
  nodes:
    - id: receiver
      type: receiver.http
      config:
        url: https://example.invalid/api
        method: POST
        timeoutSeconds: 30
        password: "supersecretvalue123"
  edges:
    - from: sender-http
      to: receiver
  errorHandling:
    defaultExceptionSubprocess:
      steps:
        - id: log-error
          type: log.message
          config: {level: ERROR, message: failed}
"""
    )
    project = Project.load(project_dir)
    errors, _ = run_rule_validators(project)
    assert any("OIW-E002" in e for e in errors), f"expected OIW-E002 in: {errors}"


def test_oiw_e003_unbounded_splitter(tmp_path: Path) -> None:
    project_dir = tmp_path / "splitter-test"
    project_dir.mkdir()
    (project_dir / "oiw.yaml").write_text(
        """apiVersion: oiw.dev/v1alpha1
kind: IntegrationProject
metadata:
  id: splitter-test
  name: Splitter Test
  created: "1970-01-01T00:00:00Z"
spec:
  package: package/package.yaml
  targetProfiles: [sap-cloud-integration-2026-07]
  minimumCompilerVersion: 0.1.0
"""
    )
    (project_dir / "flows" / "x").mkdir(parents=True)
    (project_dir / "flows" / "x" / "flow.yaml").write_text(
        """apiVersion: oiw.dev/v1alpha1
kind: IntegrationFlow
metadata: {id: x, name: x, version: 1}
spec:
  entrypoints:
    - id: sender-http
      type: sender.http
      config: {path: /x, methods: [POST]}
  nodes:
    - id: split
      type: splitter.general
      config: {}
    - id: receiver
      type: receiver.http
      config: {url: https://example.invalid/api, method: POST, timeoutSeconds: 30}
  edges:
    - {from: sender-http, to: split}
    - {from: split, to: receiver}
  errorHandling:
    defaultExceptionSubprocess:
      steps:
        - id: log
          type: log.message
          config: {level: ERROR, message: failed}
"""
    )
    project = Project.load(project_dir)
    errors, _ = run_rule_validators(project)
    assert any("OIW-E003" in e for e in errors), f"expected OIW-E003 in: {errors}"


def test_oiw_e005_insecure_http(tmp_path: Path) -> None:
    project_dir = tmp_path / "insecure-test"
    project_dir.mkdir()
    (project_dir / "oiw.yaml").write_text(
        "apiVersion: oiw.dev/v1alpha1\n"
        "kind: IntegrationProject\n"
        'metadata: {id: insecure-test, name: Insecure Test, created: "1970-01-01T00:00:00Z"}\n'
        "spec: {package: package/package.yaml, targetProfiles: [sap-cloud-integration-2026-07], minimumCompilerVersion: 0.1.0}\n"
    )
    (project_dir / "flows" / "x").mkdir(parents=True)
    (project_dir / "flows" / "x" / "flow.yaml").write_text(
        """apiVersion: oiw.dev/v1alpha1
kind: IntegrationFlow
metadata: {id: x, name: x, version: 1}
spec:
  entrypoints:
    - id: sender-http
      type: sender.http
      config: {path: /x, methods: [POST]}
  nodes:
    - id: receiver
      type: receiver.http
      config: {url: http://example.invalid/api, method: POST, timeoutSeconds: 30}
  edges:
    - {from: sender-http, to: receiver}
  errorHandling:
    defaultExceptionSubprocess:
      steps:
        - id: log
          type: log.message
          config: {level: ERROR, message: failed}
"""
    )
    project = Project.load(project_dir)
    errors, _ = run_rule_validators(project)
    assert any("OIW-E005" in e for e in errors), f"expected OIW-E005 in: {errors}"
