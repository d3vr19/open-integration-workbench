"""Tests for confidentiality verification (WP-07 Track E-004)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "seed-corpus"))

from confidentiality import (  # noqa: E402
    _scan_text,
    run_confidentiality_audit,
    run_confidentiality_check,
    scan_trajectory_file,
)
from run_learning_sessions import run_learning_sessions  # noqa: E402


class TestPatternDetection:
    def test_detects_bearer_token(self) -> None:
        """Bearer tokens are flagged as critical."""
        text = "Authorization: Bearer abc123-def456-ghi789"
        findings = _scan_text(text)
        names = [f[0] for f in findings]
        assert "bearer_token" in names
        severities = [f[1] for f in findings if f[0] == "bearer_token"]
        assert "critical" in severities

    def test_detects_password(self) -> None:
        """Inline passwords are flagged as high."""
        text = "password = 's3cr3tP@ss'"
        findings = _scan_text(text)
        names = [f[0] for f in findings]
        assert any("password" in n for n in names)

    def test_detects_api_key(self) -> None:
        """API keys are flagged as high."""
        text = "api_key=abcdef0123456789ABCDEF0123456789"
        findings = _scan_text(text)
        names = [f[0] for f in findings]
        assert "api_key" in names

    def test_detects_email(self) -> None:
        """Email addresses are flagged as PII."""
        text = "Contact: john.doe@example.com"
        findings = _scan_text(text)
        names = [f[0] for f in findings]
        assert "email" in names

    def test_detects_pem_private_key(self) -> None:
        """PEM private keys are flagged as critical."""
        text = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA1234567890abcdefghijklmnopqrstuvwxyz
-----END RSA PRIVATE KEY-----"""
        findings = _scan_text(text)
        names = [f[0] for f in findings]
        assert "pem_private_key" in names

    def test_detects_credit_card(self) -> None:
        """Credit card numbers are flagged."""
        text = "Card: 4111-1111-1111-1111"
        findings = _scan_text(text)
        names = [f[0] for f in findings]
        assert "credit_card" in names

    def test_clean_text_no_findings(self) -> None:
        """Clean text produces no findings."""
        text = "Create a flow that processes orders from HTTPS to SOAP."
        findings = _scan_text(text)
        assert findings == []

    def test_does_not_match_uuid_hex_as_phone(self) -> None:
        """Random hex/numeric IDs (like session-2a3753985156) are NOT flagged as phones."""
        # This is a regression test for the phone regex being too loose.
        text = "session-2a3753985156 failed-session-2a3753985156 expert-session-2a3753985156"
        findings = _scan_text(text)
        names = [f[0] for f in findings]
        assert (
            "phone" not in names
        ), f"phone pattern incorrectly matched UUID hex: {findings}"

    def test_detects_real_phone_number(self) -> None:
        """Real phone numbers WITH separators are still detected."""
        text = "Contact: +1-555-123-4567 for support"
        findings = _scan_text(text)
        names = [f[0] for f in findings]
        assert "phone" in names


class TestScanTrajectoryFile:
    def test_clean_session_passes(self, tmp_path: Path) -> None:
        """A session with no secrets/PII has 0 findings."""
        session = tmp_path / "session-clean.yaml"
        session.write_text(
            yaml.safe_dump(
                {
                    "id": "session-clean",
                    "requirement": "Create a flow that processes orders",
                    "provenance": {
                        "source": "learning-session",
                        "reviewer": "tester",
                        "license": "Apache-2.0",
                        "isReal": True,
                    },
                    "correction_actions": [
                        {"tool": "flow.patch", "args": {"nodeId": "receiver"}}
                    ],
                }
            )
        )
        findings = scan_trajectory_file(session)
        assert findings == []

    def test_session_with_bearer_token_flagged(self, tmp_path: Path) -> None:
        """A session containing a bearer token is flagged."""
        session = tmp_path / "session-secret.yaml"
        session.write_text(
            yaml.safe_dump(
                {
                    "id": "session-secret",
                    "requirement": "Use this token: Bearer abc123-def456",
                    "provenance": {"source": "learning-session"},
                }
            )
        )
        findings = scan_trajectory_file(session)
        assert len(findings) > 0
        names = [f.pattern_name for f in findings]
        assert "bearer_token" in names
        assert all(
            f.severity == "critical"
            for f in findings
            if f.pattern_name == "bearer_token"
        )

    def test_session_with_password_in_config_flagged(self, tmp_path: Path) -> None:
        """A session with password in config is flagged."""
        session = tmp_path / "session-pw.yaml"
        session.write_text(
            yaml.safe_dump(
                {
                    "id": "session-pw",
                    "requirement": "Build a flow",
                    "correction_actions": [
                        {
                            "tool": "flow.patch",
                            "args": {"config": {"password": "s3cr3t"}},
                        }
                    ],
                }
            )
        )
        findings = scan_trajectory_file(session)
        # Key-based redaction catches 'password' key
        assert len(findings) > 0


class TestConfidentialityAudit:
    def test_audit_clean_sessions(self, tmp_path: Path) -> None:
        """Auditing 10 clean learning sessions → 0 findings."""
        # Generate sessions
        sessions_dir = tmp_path / "sessions"
        run_learning_sessions(output_dir=sessions_dir)

        report = run_confidentiality_audit(sessions_dir)
        assert report.total_files == 10
        assert report.files_passed == 10
        assert report.files_with_findings == 0
        assert report.total_findings == 0
        assert report.findings == []

    def test_audit_detects_secrets_in_synthetic_session(self, tmp_path: Path) -> None:
        """Audit detects a synthetic session with a bearer token."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir(parents=True)

        # Write a clean session
        (sessions_dir / "session-clean.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": "session-clean",
                    "requirement": "Clean requirement",
                    "provenance": {"source": "learning-session"},
                }
            )
        )

        # Write a session with a bearer token
        (sessions_dir / "session-bad.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": "session-bad",
                    "requirement": "Use Bearer abc123-def456-ghi789 to authenticate",
                    "provenance": {"source": "learning-session"},
                }
            )
        )

        report = run_confidentiality_audit(sessions_dir)
        assert report.total_files == 2
        assert report.files_passed == 1
        assert report.files_with_findings == 1
        assert report.total_findings > 0
        assert "bearer_token" in report.by_pattern
        assert "critical" in report.by_severity

    def test_save_audit_report_yaml(self, tmp_path: Path) -> None:
        """Audit report saves as valid YAML."""
        from confidentiality import save_audit_report, ConfidentialityReport

        report = ConfidentialityReport(
            total_files=10,
            files_passed=10,
            files_with_findings=0,
            total_findings=0,
        )
        out = save_audit_report(report, tmp_path / "audit.yaml")
        assert out.is_file()
        doc = yaml.safe_load(out.read_text())
        assert doc["kind"] == "ConfidentialityAuditReport"
        assert doc["spec"]["totalFiles"] == 10
        assert doc["spec"]["totalFindings"] == 0

    def test_run_confidentiality_check_passes_for_generated_sessions(
        self, tmp_path: Path
    ) -> None:
        """End-to-end: generated sessions all pass confidentiality check."""
        sessions_dir = tmp_path / "sessions"
        run_learning_sessions(output_dir=sessions_dir)

        result = run_confidentiality_check(
            learning_sessions_dir=sessions_dir,
            output_path=tmp_path / "audit.yaml",
        )
        assert result["passed"] is True
        assert result["report"]["totalFindings"] == 0
        assert (tmp_path / "audit.yaml").is_file()
