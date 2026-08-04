"""Provenance tagging + verification (WP-07 Track E-001).

Spec ref: §15.12 (Knowledge Governance).

Every trajectory and insight produced by WP-07 must have provenance:
  - source: learning-session | sap-codejam | blog-post | synthetic | etc.
  - reviewer: human reviewer name (or "automated-seed-pipeline" for synthetic)
  - license: Apache-2.0 (or other SPDX identifier)
  - isReal: True for real public artifacts, False for synthetic
  - artifactUrl: original URL (for real artifacts)
  - reviewDate: ISO date when the provenance was attached
  - confidence: 0.0–1.0

This module:
  1. Provides a `ProvenanceTagger` that attaches provenance to trajectories
     and insights.
  2. Provides a `verify_provenance` function that audits all knowledge in
     the EMG and reports missing fields.
  3. Provides a CLI entry point: `oiw emg provenance` (smoke test).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "seed-corpus"))


# --------------------------------------------------------------------------- #
# Provenance schema
# --------------------------------------------------------------------------- #


@dataclass
class Provenance:
    """Provenance metadata for a trajectory or insight.

    Spec ref: §15.12.
    """

    source: str  # learning-session | sap-codejam | blog-post | synthetic | oiw-example
    reviewer: str
    license_spdx: str = "Apache-2.0"
    is_real: bool = False
    artifact_url: str | None = None
    review_date: str = field(
        default_factory=lambda: datetime.now(tz=UTC).date().isoformat()
    )
    confidence: float = 0.8
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "source": self.source,
            "reviewer": self.reviewer,
            "license": self.license_spdx,
            "isReal": self.is_real,
            "reviewDate": self.review_date,
            "confidence": self.confidence,
        }
        if self.artifact_url:
            d["artifactUrl"] = self.artifact_url
        if self.extra:
            for k, v in self.extra.items():
                d[k] = v
        return d


# --------------------------------------------------------------------------- #
# Provenance tagger
# --------------------------------------------------------------------------- #


class ProvenanceTagger:
    """Attaches provenance metadata to trajectories and insights."""

    def __init__(self, reviewer: str = "hehenaice"):
        self.reviewer = reviewer

    def tag_learning_session(
        self,
        failure_mode_id: str,
        archetype: str,
        confidence: float = 0.85,
    ) -> Provenance:
        """Provenance for a learning session trajectory pair."""
        return Provenance(
            source="learning-session",
            reviewer=self.reviewer,
            license_spdx="Apache-2.0",
            is_real=True,
            review_date=datetime.now(tz=UTC).date().isoformat(),
            confidence=confidence,
            extra={
                "failureMode": failure_mode_id,
                "archetype": archetype,
            },
        )

    def tag_sap_codejam(self, artifact_url: str, confidence: float = 0.9) -> Provenance:
        """Provenance for a SAP CodeJam artifact trajectory."""
        return Provenance(
            source="sap-codejam",
            reviewer=self.reviewer,
            license_spdx="Apache-2.0",
            is_real=True,
            artifact_url=artifact_url,
            confidence=confidence,
        )

    def tag_blog_post(self, blog_url: str, confidence: float = 0.75) -> Provenance:
        """Provenance for a blog-post-derived pattern."""
        return Provenance(
            source="blog-post",
            reviewer=self.reviewer,
            license_spdx="Apache-2.0",
            is_real=True,
            artifact_url=blog_url,
            confidence=confidence,
        )

    def tag_synthetic(
        self,
        origin: str = "synthetic",
        confidence: float = 0.6,
    ) -> Provenance:
        """Provenance for a synthetic trajectory."""
        return Provenance(
            source=origin,
            reviewer="automated-seed-pipeline",
            license_spdx="Apache-2.0",
            is_real=False,
            confidence=confidence,
        )

    def tag_oiw_example(self, confidence: float = 0.85) -> Provenance:
        """Provenance for an OIW reference example."""
        return Provenance(
            source="oiw-example",
            reviewer=self.reviewer,
            license_spdx="Apache-2.0",
            is_real=True,
            confidence=confidence,
        )


# --------------------------------------------------------------------------- #
# Provenance verification
# --------------------------------------------------------------------------- #


@dataclass
class ProvenanceAuditResult:
    """Result of auditing provenance across the EMG."""

    total_artifacts: int = 0
    with_provenance: int = 0
    missing_provenance: int = 0
    missing_fields: list[dict[str, Any]] = field(default_factory=list)
    by_source: dict[str, int] = field(default_factory=dict)
    real_count: int = 0
    synthetic_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalArtifacts": self.total_artifacts,
            "withProvenance": self.with_provenance,
            "missingProvenance": self.missing_provenance,
            "missingFields": self.missing_fields,
            "bySource": self.by_source,
            "realCount": self.real_count,
            "syntheticCount": self.synthetic_count,
        }


REQUIRED_PROVENANCE_FIELDS = ["source", "reviewer", "license", "isReal"]


def verify_provenance(
    learning_sessions_dir: Path | str | None = None,
    avoid_patterns_yaml: Path | str | None = None,
) -> ProvenanceAuditResult:
    """Audit provenance across all WP-07 knowledge artifacts.

    Checks:
      - Every learning session has provenance with required fields
      - Every avoid pattern has provenance with required fields
    """
    if learning_sessions_dir is None:
        learning_sessions_dir = (
            REPO_ROOT / "packages" / "seed-corpus" / "learning-sessions"
        )
    if avoid_patterns_yaml is None:
        avoid_patterns_yaml = (
            REPO_ROOT / "packages" / "seed-corpus" / "negative-knowledge.yaml"
        )
    learning_sessions_dir = Path(learning_sessions_dir)
    avoid_patterns_yaml = Path(avoid_patterns_yaml)

    result = ProvenanceAuditResult()

    # 1. Learning sessions
    if learning_sessions_dir.is_dir():
        for sf in sorted(learning_sessions_dir.glob("session-*.yaml")):
            result.total_artifacts += 1
            try:
                data = yaml.safe_load(sf.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                result.missing_provenance += 1
                result.missing_fields.append(
                    {
                        "file": str(sf),
                        "error": "yaml parse error",
                    }
                )
                continue

            prov = data.get("provenance") or {}
            missing = [f for f in REQUIRED_PROVENANCE_FIELDS if f not in prov]
            if missing:
                result.missing_provenance += 1
                result.missing_fields.append(
                    {
                        "file": str(sf),
                        "missing": missing,
                    }
                )
            else:
                result.with_provenance += 1
                source = prov.get("source", "unknown")
                result.by_source[source] = result.by_source.get(source, 0) + 1
                if prov.get("isReal"):
                    result.real_count += 1
                else:
                    result.synthetic_count += 1

    # 2. Avoid patterns
    if avoid_patterns_yaml.is_file():
        try:
            doc = yaml.safe_load(avoid_patterns_yaml.read_text(encoding="utf-8"))
            for ap in doc.get("spec", {}).get("avoidPatterns", []):
                result.total_artifacts += 1
                prov = ap.get("provenance") or {}
                missing = [f for f in REQUIRED_PROVENANCE_FIELDS if f not in prov]
                if missing:
                    result.missing_provenance += 1
                    result.missing_fields.append(
                        {
                            "pattern": ap.get("id"),
                            "missing": missing,
                        }
                    )
                else:
                    result.with_provenance += 1
                    source = prov.get("source", "unknown")
                    result.by_source[source] = result.by_source.get(source, 0) + 1
                    if prov.get("isReal"):
                        result.real_count += 1
                    else:
                        result.synthetic_count += 1
        except Exception as exc:  # noqa: BLE001
            result.missing_fields.append(
                {
                    "file": str(avoid_patterns_yaml),
                    "error": str(exc),
                }
            )

    return result


def run_provenance_audit() -> dict[str, Any]:
    """Run the full provenance audit and return a summary."""
    result = verify_provenance()
    return result.to_dict()


if __name__ == "__main__":
    summary = run_provenance_audit()
    print(yaml.safe_dump(summary, sort_keys=False, default_flow_style=False))
