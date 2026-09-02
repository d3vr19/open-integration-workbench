"""Tests for seed corpus security audit (WP-06 Track H Task H-001)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from security_audit import audit_seed_corpus_security


class TestSecurityAudit:
    def test_audit_empty_corpus_passes(self, tmp_path: Path) -> None:
        """Empty corpus → PASS."""
        report = audit_seed_corpus_security(corpus_dir=tmp_path / "empty")
        assert report["status"] == "PASS"
        assert report["secretsFound"] == 0

    def test_audit_clean_corpus_passes(self, tmp_path: Path) -> None:
        """Corpus with no secrets → PASS."""
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "flow.yaml").write_text(
            "apiVersion: oiw.dev/v1alpha1\nkind: IntegrationFlow\n"
        )
        report = audit_seed_corpus_security(corpus_dir=corpus)
        assert report["status"] == "PASS"
        assert report["filesScanned"] >= 1
        assert report["secretsFound"] == 0

    def test_audit_finds_secrets(self, tmp_path: Path) -> None:
        """Corpus with secrets → FAIL."""
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "config.yaml").write_text('password = "supersecret123"\n')
        report = audit_seed_corpus_security(corpus_dir=corpus)
        assert report["status"] == "FAIL"
        assert report["secretsFound"] > 0
        assert any(f["type"] == "secret" for f in report["findings"])

    def test_audit_report_persisted(self, tmp_path: Path) -> None:
        """Audit report is saved to disk."""
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "flow.yaml").write_text("apiVersion: oiw.dev/v1alpha1\n")
        audit_seed_corpus_security(corpus_dir=corpus, report_dir=tmp_path / "audit")
        report_file = tmp_path / "audit" / "security-audit-report.yaml"
        assert report_file.is_file()
        loaded = yaml.safe_load(report_file.read_text())
        assert "status" in loaded
        assert "filesScanned" in loaded

    def test_audit_flags_customer_urls(self, tmp_path: Path) -> None:
        """Corpus with non-example.com URLs → flagged as customer data."""
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "flow.yaml").write_text("url: https://mycompany.sap.com/api\n")
        report = audit_seed_corpus_security(corpus_dir=corpus)
        assert report["customerDataFound"] > 0
