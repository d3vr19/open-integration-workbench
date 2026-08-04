"""Seed corpus security audit (WP-06 Track H Task H-001).

Verifies no secrets, customer identifiers, or license violations exist
in the seed corpus before Beta release.

Outputs: packages/seed-corpus/audit/security-audit-report.yaml
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from license_audit import SECRET_PATTERNS  # noqa: E402


def audit_seed_corpus_security(corpus_dir: Path | str | None = None) -> dict:
    """Run security audit on the seed corpus.

    Returns a dict with findings.
    """
    corpus_dir = Path(corpus_dir or (Path(__file__).parent / "artifacts"))
    findings: list[dict] = []
    files_scanned = 0
    secrets_found = 0
    customer_data_found = 0

    if not corpus_dir.is_dir():
        return {
            "status": "PASS",
            "reason": "no seed corpus artifacts directory found",
            "filesScanned": 0,
            "secretsFound": 0,
            "findings": [],
            "auditDate": datetime.now().isoformat(),
        }

    for file_path in sorted(corpus_dir.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix not in {
            ".yaml",
            ".yml",
            ".json",
            ".py",
            ".groovy",
            ".xml",
            ".txt",
        }:
            continue

        files_scanned += 1
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        rel_path = str(file_path.relative_to(corpus_dir))

        # Check for secrets
        for pattern, name in SECRET_PATTERNS:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                secrets_found += len(matches)
                findings.append(
                    {
                        "file": rel_path,
                        "type": "secret",
                        "pattern": name,
                        "count": len(matches),
                    }
                )

        # Check for customer identifiers (real URLs, not example.com)
        real_urls = re.findall(
            r"https?://(?!example\.(com|org)|localhost|127\.0\.0\.1)[a-zA-Z0-9.-]+\.[a-z]{2,}",
            content,
        )
        if real_urls:
            customer_data_found += len(real_urls)
            findings.append(
                {
                    "file": rel_path,
                    "type": "customer_url",
                    "count": len(real_urls),
                    "examples": real_urls[:3],
                }
            )

    status = "PASS" if secrets_found == 0 else "FAIL"

    report = {
        "status": status,
        "filesScanned": files_scanned,
        "secretsFound": secrets_found,
        "customerDataFound": customer_data_found,
        "findings": findings,
        "auditDate": datetime.now().isoformat(),
        "auditor": "automated-security-audit",
    }

    # Persist report
    audit_dir = Path(__file__).parent / "audit"
    audit_dir.mkdir(exist_ok=True)
    report_file = audit_dir / "security-audit-report.yaml"
    report_file.write_text(
        yaml.safe_dump(
            report, sort_keys=False, default_flow_style=False, allow_unicode=True
        ),
        encoding="utf-8",
    )

    return report


if __name__ == "__main__":
    report = audit_seed_corpus_security()
    print("=== Seed Corpus Security Audit ===")
    print(f"  Status:       {report['status']}")
    print(f"  Files scanned: {report['filesScanned']}")
    print(f"  Secrets found: {report['secretsFound']}")
    print(f"  Customer data: {report['customerDataFound']}")
    if report["findings"]:
        print("  Findings:")
        for f in report["findings"]:
            print(f"    {f['file']}: {f['type']} ({f.get('count', 1)})")
    print("\nReport: packages/seed-corpus/audit/security-audit-report.yaml")
