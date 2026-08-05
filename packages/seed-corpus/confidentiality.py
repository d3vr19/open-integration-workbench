"""Confidentiality verification for learning session trajectories (WP-07 Track E-004).

Spec ref: §15.12 (Knowledge Governance), §15.17 (Secret Redaction).

Verifies that no learning session trajectory contains:
  - Secrets (bearer tokens, API keys, passwords, private keys)
  - Customer identifiers (tenant URLs, customer IDs)
  - Tenant URLs (real SAP hostnames)
  - Personal data (email addresses, phone numbers)

Runs the existing Redactor in scan-only mode (no replacement) to detect
patterns that WOULD be redacted, plus additional checks for PII.

Acceptance (WP-07 Task E-004):
  - All learning session trajectories pass redaction check
  - Zero secrets in any trajectory
  - Zero customer identifiers in any trajectory
  - Redaction report saved
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "seed-corpus"))

from oiw.agent.redaction import PATTERNS  # noqa: E402


# --------------------------------------------------------------------------- #
# PII detection (additional to Redactor — these aren't secrets but are PII)
# --------------------------------------------------------------------------- #

PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "email"),
    # Phone numbers (international + US)
    (
        re.compile(r"\+?\d{1,3}?[-.\s]?\(?\d{1,4}?\)?[-.\s]?\d{3,4}[-.\s]?\d{4}\b"),
        "phone",
    ),
    # Credit card numbers (basic pattern)
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "credit_card"),
    # Social security numbers (US format)
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "ssn"),
    # Real customer IDs (CID-12345, CUST-67890, etc.)
    (re.compile(r"\b(?:CID|CUST|CUSTOMER)[-_]?\d{4,}\b", re.IGNORECASE), "customer_id"),
    # Real SAP tenant URLs (only known patterns)
    (re.compile(r"https?://[a-zA-Z0-9.\-]+\.sap(?:hana)?\.com"), "sap_tenant_url"),
    # IP addresses (potential internal network leaks)
    (
        re.compile(r"\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b"),
        "private_ip",
    ),
]


@dataclass
class ConfidentialityFinding:
    """A single confidentiality violation found in a trajectory."""

    file: str
    field_path: str  # dotted path to the offending field
    pattern_name: str  # e.g. "bearer_token", "email", "password"
    match_snippet: str  # first 80 chars of the match (for debugging)
    severity: str  # "critical" | "high" | "medium" | "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "fieldPath": self.field_path,
            "pattern": self.pattern_name,
            "snippet": self.match_snippet,
            "severity": self.severity,
        }


@dataclass
class ConfidentialityReport:
    """Result of scanning all learning session trajectories."""

    total_files: int = 0
    files_passed: int = 0
    files_with_findings: int = 0
    total_findings: int = 0
    findings: list[ConfidentialityFinding] = field(default_factory=list)
    by_severity: dict[str, int] = field(default_factory=dict)
    by_pattern: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalFiles": self.total_files,
            "filesPassed": self.files_passed,
            "filesWithFindings": self.files_with_findings,
            "totalFindings": self.total_findings,
            "findings": [f.to_dict() for f in self.findings],
            "bySeverity": self.by_severity,
            "byPattern": self.by_pattern,
        }


# Map each Redactor pattern to a severity + name
_REDACTOR_PATTERN_INFO = [
    ("pem_private_key", "critical"),
    ("bearer_token", "critical"),
    ("api_key", "high"),
    ("password_quoted", "high"),
    ("password_unquoted", "high"),
    ("client_secret", "high"),
    ("sap_internal_hostname", "medium"),
    ("long_hex_token", "medium"),
    ("jdbc_connection_string", "high"),
]


def _scan_text(text: str) -> list[tuple[str, str, str]]:
    """Scan a text string for redaction patterns.

    Returns a list of (pattern_name, severity, snippet) tuples.
    """
    findings: list[tuple[str, str, str]] = []

    # Check Redactor patterns (secrets)
    for i, (pattern, _) in enumerate(PATTERNS):
        name = (
            _REDACTOR_PATTERN_INFO[i][0]
            if i < len(_REDACTOR_PATTERN_INFO)
            else f"redactor_{i}"
        )
        severity = (
            _REDACTOR_PATTERN_INFO[i][1]
            if i < len(_REDACTOR_PATTERN_INFO)
            else "medium"
        )
        for match in pattern.finditer(text):
            snippet = match.group(0)[:80]
            findings.append((name, severity, snippet))

    # Check PII patterns
    for pattern, name in PII_PATTERNS:
        severity = (
            "high"
            if name in ("email", "credit_card", "ssn", "customer_id")
            else "medium"
        )
        if name == "sap_tenant_url":
            severity = "high"
        if name == "private_ip":
            severity = "low"
        if name == "phone":
            severity = "medium"
        for match in pattern.finditer(text):
            snippet = match.group(0)[:80]
            findings.append((name, severity, snippet))

    return findings


def _scan_value(value: Any, path: str = "") -> list[tuple[str, str, str, str]]:
    """Recursively scan a value, returning (path, pattern_name, severity, snippet)."""
    results: list[tuple[str, str, str, str]] = []

    if isinstance(value, str):
        for name, severity, snippet in _scan_text(value):
            results.append((path, name, severity, snippet))
    elif isinstance(value, dict):
        for k, v in value.items():
            child_path = f"{path}.{k}" if path else k
            # Key-based detection: if the key suggests a secret, flag the value
            if _is_secret_key(k) and v is not None and v != "":
                snippet = str(v)[:80] if not isinstance(v, dict | list) else "<nested>"
                results.append((child_path, f"secret_key:{k}", "high", snippet))
            else:
                results.extend(_scan_value(v, child_path))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            child_path = f"{path}[{i}]"
            results.extend(_scan_value(item, child_path))

    return results


def _is_secret_key(key: str) -> bool:
    """Check if a dict key name suggests it holds a secret.

    Excludes 'credentialRef' / 'credential_ref' which are the SAFE
    indirection mechanism (the agent uses these to AVOID inline secrets).
    """
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    # credentialRef / credential_ref are safe (they replace inline secrets)
    if lowered in ("credentialref", "credential_ref", "credentialrefid"):
        return False
    secret_keywords = (
        "password",
        "passwd",
        "secret",
        "clientsecret",
        "client_secret",
        "apikey",
        "api_key",
        "accesstoken",
        "access_token",
        "refreshtoken",
        "refresh_token",
        "bearer",
        "authorization",
        "credential",
        "privatekey",
        "private_key",
    )
    return any(kw in lowered for kw in secret_keywords)


def scan_trajectory_file(file_path: Path) -> list[ConfidentialityFinding]:
    """Scan a single trajectory YAML file for confidentiality violations."""
    findings: list[ConfidentialityFinding] = []

    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        findings.append(
            ConfidentialityFinding(
                file=str(file_path),
                field_path="<parse_error>",
                pattern_name="yaml_parse_error",
                match_snippet=str(exc)[:80],
                severity="low",
            )
        )
        return findings

    if not isinstance(data, dict):
        return findings

    raw_findings = _scan_value(data)
    for path, name, severity, snippet in raw_findings:
        findings.append(
            ConfidentialityFinding(
                file=str(file_path),
                field_path=path,
                pattern_name=name,
                match_snippet=snippet,
                severity=severity,
            )
        )

    return findings


def run_confidentiality_audit(
    learning_sessions_dir: Path | str | None = None,
) -> ConfidentialityReport:
    """Audit all learning session trajectories for confidentiality.

    Args:
        learning_sessions_dir: Directory containing session-*.yaml files.

    Returns:
        ConfidentialityReport with findings.
    """
    if learning_sessions_dir is None:
        learning_sessions_dir = (
            REPO_ROOT / "packages" / "seed-corpus" / "learning-sessions"
        )
    learning_sessions_dir = Path(learning_sessions_dir)

    report = ConfidentialityReport()

    if not learning_sessions_dir.is_dir():
        return report

    for session_file in sorted(learning_sessions_dir.glob("session-*.yaml")):
        report.total_files += 1
        findings = scan_trajectory_file(session_file)
        if findings:
            report.files_with_findings += 1
            report.findings.extend(findings)
            for f in findings:
                report.by_severity[f.severity] = (
                    report.by_severity.get(f.severity, 0) + 1
                )
                report.by_pattern[f.pattern_name] = (
                    report.by_pattern.get(f.pattern_name, 0) + 1
                )
        else:
            report.files_passed += 1

    report.total_findings = len(report.findings)
    return report


def save_audit_report(
    report: ConfidentialityReport,
    output_path: Path | str | None = None,
) -> Path:
    """Save the audit report to a YAML file.

    Default: packages/seed-corpus/audit/confidentiality-audit-wp07.yaml
    """
    if output_path is None:
        output_path = (
            REPO_ROOT
            / "packages"
            / "seed-corpus"
            / "audit"
            / "confidentiality-audit-wp07.yaml"
        )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "ConfidentialityAuditReport",
        "metadata": {
            "version": "0.1.0",
            "created": "2026-08-05",
            "description": "WP-07 Track E-004: confidentiality check on learning session trajectories",
        },
        "spec": report.to_dict(),
    }
    output_path.write_text(
        yaml.safe_dump(
            doc, sort_keys=False, default_flow_style=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
    return output_path


def run_confidentiality_check(
    learning_sessions_dir: Path | str | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Run the full confidentiality audit + save the report.

    Returns the audit summary as a dict.
    """
    report = run_confidentiality_audit(learning_sessions_dir)
    out = save_audit_report(report, output_path)
    return {
        "report": report.to_dict(),
        "outputPath": str(out),
        "passed": report.total_findings == 0,
    }


if __name__ == "__main__":
    summary = run_confidentiality_check()
    print(yaml.safe_dump(summary, sort_keys=False, default_flow_style=False))
