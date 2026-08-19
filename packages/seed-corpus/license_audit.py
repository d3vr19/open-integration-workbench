"""License audit framework for seed corpus (WP-06 Task A-001).

Spec ref: §15.14 (Seed Corpus), §31 (Documentation).

Audits source repositories for license compatibility before ingestion.
Outputs audit reports to packages/seed-corpus/audit/{source_id}/.

Allowlist: Apache-2.0, MIT, BSD-2-Clause, BSD-3-Clause, SAP Sample Code License.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# Allowlist of approved licenses (spec §15.14)
LICENSE_ALLOWLIST = {
    "Apache-2.0",
    "MIT",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "SAP Sample Code License",
    "Apache 2.0",
    "apache-2.0",
}

# SPDX identifier patterns
SPDX_PATTERNS = [
    (r"Apache License.*Version 2\.0", "Apache-2.0"),
    (r"MIT License", "MIT"),
    (r"BSD 2-Clause", "BSD-2-Clause"),
    (r"BSD 3-Clause", "BSD-3-Clause"),
    (r"SAP Sample Code License", "SAP Sample Code License"),
]

# Secret detection patterns (reused from agent.redaction)
SECRET_PATTERNS = [
    (r"password\s*[=:]\s*['\"]\S+['\"]", "password"),
    (r"clientSecret\s*[=:]\s*['\"]\S+['\"]", "clientSecret"),
    (r"apiKey\s*[=:]\s*['\"]\S+['\"]", "apiKey"),
    (r"Bearer\s+[A-Za-z0-9\-._~+/]+", "bearer token"),
    (r"-----BEGIN.*PRIVATE KEY-----", "private key"),
]


@dataclass
class ArtifactAudit:
    """Audit result for a single artifact file."""

    path: str
    contains_secrets: bool = False
    secret_findings: list[str] = field(default_factory=list)
    contains_customer_data: bool = False
    approved: bool = True


@dataclass
class AuditReport:
    """Full audit report for a source."""

    source_id: str
    source_name: str
    source_url: str
    license: str = "UNKNOWN"
    spdx_id: str = "UNKNOWN"
    approved: bool = False
    artifacts: list[ArtifactAudit] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    auditor: str = "automated"
    audit_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "sourceName": self.source_name,
            "sourceUrl": self.source_url,
            "license": self.license,
            "spdxId": self.spdx_id,
            "approved": self.approved,
            "artifacts": [
                {
                    "path": a.path,
                    "containsSecrets": a.contains_secrets,
                    "secretFindings": a.secret_findings,
                    "containsCustomerData": a.contains_customer_data,
                    "approved": a.approved,
                }
                for a in self.artifacts
            ],
            "rejectionReasons": self.rejection_reasons,
            "auditor": self.auditor,
            "auditDate": self.audit_date,
        }


class LicenseAuditor:
    """Audits source repositories for license + secret compliance."""

    def __init__(self, audit_dir: Path | str = "packages/seed-corpus/audit"):
        self.audit_dir = Path(audit_dir)

    def audit_local_repo(
        self,
        repo_path: Path | str,
        source_id: str,
        source_name: str,
        source_url: str,
    ) -> AuditReport:
        """Audit a locally cloned repository.

        Args:
            repo_path: Path to the cloned repo.
            source_id: Short ID for the source.
            source_name: Human-readable name.
            source_url: Original URL.

        Returns:
            AuditReport with license + secret findings.
        """
        repo_path = Path(repo_path)
        report = AuditReport(
            source_id=source_id,
            source_name=source_name,
            source_url=source_url,
        )

        # 1. Detect license
        license_text, spdx_id = self._detect_license(repo_path)
        report.license = license_text
        report.spdx_id = spdx_id

        if spdx_id in LICENSE_ALLOWLIST or license_text in LICENSE_ALLOWLIST:
            report.approved = True
        else:
            report.approved = False
            report.rejection_reasons.append(
                f"license '{license_text}' (SPDX: {spdx_id}) not in allowlist"
            )

        # 2. Scan for secrets in relevant files
        scan_extensions = {
            ".py",
            ".js",
            ".ts",
            ".json",
            ".yaml",
            ".yml",
            ".xml",
            ".groovy",
            ".properties",
            ".txt",
        }
        for file_path in sorted(repo_path.rglob("*")):
            if not file_path.is_file():
                continue
            # Skip .git, node_modules, etc.
            if any(
                part in {".git", "node_modules", "__pycache__", ".venv"}
                for part in file_path.parts
            ):
                continue
            if file_path.suffix not in scan_extensions:
                continue

            artifact = ArtifactAudit(path=str(file_path.relative_to(repo_path)))

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            # Check for secrets
            for pattern, name in SECRET_PATTERNS:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    artifact.contains_secrets = True
                    artifact.secret_findings.append(
                        f"{name}: {len(matches)} occurrence(s)"
                    )
                    artifact.approved = False

            # Check for customer data (example.com URLs are OK — they're placeholders)
            if "example.com" in content or "example.org" in content:
                artifact.contains_customer_data = True  # flagged but not rejected

            report.artifacts.append(artifact)

        if any(a.contains_secrets for a in report.artifacts):
            report.approved = False
            report.rejection_reasons.append("secrets found in artifact files")

        # 3. Persist report
        self._persist_report(report)

        return report

    def audit_synthetic_artifact(
        self,
        artifact_id: str,
        artifact_name: str,
        artifact_dir: Path | str,
    ) -> AuditReport:
        """Audit a synthetic artifact (created by us, not from external source).

        Synthetic artifacts are auto-approved because:
        - We created them (license = Apache-2.0 by default)
        - No secrets by construction
        - No customer data
        """
        artifact_dir = Path(artifact_dir)
        report = AuditReport(
            source_id=f"synthetic-{artifact_id}",
            source_name=artifact_name,
            source_url=f"oiw://synthetic/{artifact_id}",
            license="Apache-2.0",
            spdx_id="Apache-2.0",
            approved=True,
            auditor="synthetic-auto-approve",
        )

        # Still scan for secrets (defense in depth)
        for file_path in sorted(artifact_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if any(part in {".git", "__pycache__"} for part in file_path.parts):
                continue
            artifact = ArtifactAudit(path=str(file_path.relative_to(artifact_dir)))
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pattern, name in SECRET_PATTERNS:
                if re.search(pattern, content, re.IGNORECASE):
                    artifact.contains_secrets = True
                    artifact.secret_findings.append(name)
                    artifact.approved = False
                    report.approved = False
                    report.rejection_reasons.append(
                        f"secret in {artifact.path}: {name}"
                    )
            report.artifacts.append(artifact)

        self._persist_report(report)
        return report

    def _detect_license(self, repo_path: Path) -> tuple[str, str]:
        """Detect the license from LICENSE/LICENCE/COPYING file."""
        for name in ["LICENSE", "LICENCE", "COPYING", "LICENSE.md", "LICENSE.txt"]:
            license_file = repo_path / name
            if license_file.is_file():
                text = license_file.read_text(encoding="utf-8", errors="replace")
                for pattern, spdx in SPDX_PATTERNS:
                    if re.search(pattern, text, re.IGNORECASE):
                        return spdx, spdx
                # If file exists but no pattern matched
                return f"Unknown (file: {name})", "UNKNOWN"
        return "No LICENSE file", "UNKNOWN"

    def _persist_report(self, report: AuditReport) -> None:
        """Write the audit report to disk."""
        out_dir = self.audit_dir / report.source_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "audit-report.yaml"
        out_file.write_text(
            yaml.safe_dump(
                report.to_dict(),
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )


def audit_oiw_examples(audit_dir: Path | str | None = None) -> list[AuditReport]:
    """Audit the OIW example projects (order-to-s4, sftp-order-drop).

    These are our own examples (Apache-2.0) — treated as synthetic
    (auto-approved) since they're part of the OIW repo.
    """
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent
    auditor = LicenseAuditor(audit_dir=audit_dir or (Path(__file__).parent / "audit"))

    reports = []
    for example_name in ["order-to-s4", "sftp-order-drop"]:
        example_path = REPO_ROOT / "examples" / example_name
        if example_path.is_dir():
            report = auditor.audit_synthetic_artifact(
                artifact_id=f"oiw-example-{example_name}",
                artifact_name=f"OIW Example: {example_name}",
                artifact_dir=example_path,
            )
            reports.append(report)

    return reports


__all__ = [
    "LICENSE_ALLOWLIST",
    "ArtifactAudit",
    "AuditReport",
    "LicenseAuditor",
    "audit_oiw_examples",
]
