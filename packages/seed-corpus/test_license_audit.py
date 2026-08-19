"""Tests for license audit framework (WP-06 Task A-001).

Covers:
  - Audit OIW examples → approved (Apache-2.0)
  - Audit a repo with no LICENSE → rejected
  - Audit a repo with secrets → artifacts flagged
  - Audit synthetic artifact → auto-approved
  - Audit report persisted to disk
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from license_audit import (
    LicenseAuditor,
    audit_oiw_examples,
)


class TestLicenseAuditor:
    def test_audit_oiw_examples_approved(self, tmp_path: Path) -> None:
        """OIW examples (Apache-2.0) → approved."""
        reports = audit_oiw_examples(audit_dir=tmp_path / "audit")
        assert len(reports) >= 1
        for report in reports:
            assert report.approved
            assert report.spdx_id == "Apache-2.0"

    def test_audit_repo_no_license_rejected(self, tmp_path: Path) -> None:
        """A repo with no LICENSE file → rejected."""
        repo = tmp_path / "no-license-repo"
        repo.mkdir()
        (repo / "README.md").write_text("# Test repo")

        auditor = LicenseAuditor(audit_dir=tmp_path / "audit")
        report = auditor.audit_local_repo(
            repo_path=repo,
            source_id="test-no-license",
            source_name="Test No License",
            source_url="https://example.com/test",
        )
        assert not report.approved
        assert any(
            "not in allowlist" in r or "No LICENSE" in r
            for r in report.rejection_reasons
        )

    def test_audit_repo_with_secrets_flagged(self, tmp_path: Path) -> None:
        """A repo with secrets in files → artifacts flagged."""
        repo = tmp_path / "secret-repo"
        repo.mkdir()
        (repo / "LICENSE").write_text("Apache License, Version 2.0\n")
        (repo / "config.py").write_text('password = "supersecret123"\n')

        auditor = LicenseAuditor(audit_dir=tmp_path / "audit")
        report = auditor.audit_local_repo(
            repo_path=repo,
            source_id="test-secrets",
            source_name="Test Secrets",
            source_url="https://example.com/test",
        )
        assert not report.approved
        assert any(a.contains_secrets for a in report.artifacts)

    def test_audit_apache_repo_approved(self, tmp_path: Path) -> None:
        """A repo with Apache-2.0 LICENSE → approved."""
        repo = tmp_path / "apache-repo"
        repo.mkdir()
        (repo / "LICENSE").write_text(
            "Apache License, Version 2.0\n\n"
            "http://www.apache.org/licenses/LICENSE-2.0\n"
        )
        (repo / "flow.yaml").write_text(
            "apiVersion: oiw.dev/v1alpha1\nkind: IntegrationFlow\n"
        )

        auditor = LicenseAuditor(audit_dir=tmp_path / "audit")
        report = auditor.audit_local_repo(
            repo_path=repo,
            source_id="test-apache",
            source_name="Test Apache",
            source_url="https://example.com/test",
        )
        assert report.approved
        assert report.spdx_id == "Apache-2.0"

    def test_audit_synthetic_auto_approved(self, tmp_path: Path) -> None:
        """Synthetic artifact → auto-approved (Apache-2.0 by default)."""
        artifact_dir = tmp_path / "synthetic-artifact"
        artifact_dir.mkdir()
        (artifact_dir / "flow.yaml").write_text("apiVersion: oiw.dev/v1alpha1\n")

        auditor = LicenseAuditor(audit_dir=tmp_path / "audit")
        report = auditor.audit_synthetic_artifact(
            artifact_id="test-synth",
            artifact_name="Test Synthetic",
            artifact_dir=artifact_dir,
        )
        assert report.approved
        assert report.license == "Apache-2.0"
        assert report.auditor == "synthetic-auto-approve"

    def test_audit_report_persisted_to_disk(self, tmp_path: Path) -> None:
        """Audit report is written to disk as YAML."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "LICENSE").write_text("MIT License\n\nCopyright (c) 2026\n")
        (repo / "main.py").write_text("print('hello')\n")

        audit_dir = tmp_path / "audit"
        auditor = LicenseAuditor(audit_dir=audit_dir)
        auditor.audit_local_repo(
            repo_path=repo,
            source_id="test-persist",
            source_name="Test Persist",
            source_url="https://example.com/test",
        )

        report_file = audit_dir / "test-persist" / "audit-report.yaml"
        assert report_file.is_file()
        loaded = yaml.safe_load(report_file.read_text(encoding="utf-8"))
        assert loaded["sourceId"] == "test-persist"
        assert loaded["spdxId"] == "MIT"
        assert loaded["approved"] is True

    def test_gpl_license_rejected(self, tmp_path: Path) -> None:
        """GPL-3.0 is not in the allowlist → rejected."""
        repo = tmp_path / "gpl-repo"
        repo.mkdir()
        (repo / "LICENSE").write_text(
            "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n"
        )
        (repo / "code.py").write_text("print('gpl')\n")

        auditor = LicenseAuditor(audit_dir=tmp_path / "audit")
        report = auditor.audit_local_repo(
            repo_path=repo,
            source_id="test-gpl",
            source_name="Test GPL",
            source_url="https://example.com/test",
        )
        assert not report.approved
        assert any("not in allowlist" in r for r in report.rejection_reasons)
