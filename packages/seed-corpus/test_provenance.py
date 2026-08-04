"""Tests for provenance tagging (WP-07 Track E-001)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from provenance import (  # noqa: E402
    ProvenanceTagger,
    REQUIRED_PROVENANCE_FIELDS,
    verify_provenance,
)
from run_learning_sessions import run_learning_sessions  # noqa: E402
from negative_knowledge import populate_negative_knowledge  # noqa: E402


class TestProvenanceTagger:
    def test_tag_learning_session(self) -> None:
        """Learning-session provenance has correct fields."""
        tagger = ProvenanceTagger(reviewer="test-reviewer")
        prov = tagger.tag_learning_session("fm-001", "paginated-api-ingestion")
        assert prov.source == "learning-session"
        assert prov.reviewer == "test-reviewer"
        assert prov.is_real is True
        assert prov.license_spdx == "Apache-2.0"
        assert prov.extra["failureMode"] == "fm-001"
        assert prov.extra["archetype"] == "paginated-api-ingestion"

    def test_tag_synthetic(self) -> None:
        """Synthetic provenance has isReal=False."""
        tagger = ProvenanceTagger()
        prov = tagger.tag_synthetic()
        assert prov.is_real is False
        assert prov.source == "synthetic"
        assert prov.reviewer == "automated-seed-pipeline"

    def test_tag_sap_codejam(self) -> None:
        """CodeJam provenance has artifact_url."""
        tagger = ProvenanceTagger()
        prov = tagger.tag_sap_codejam("https://github.com/SAP/cloud-integration")
        assert prov.is_real is True
        assert prov.artifact_url == "https://github.com/SAP/cloud-integration"

    def test_to_dict_includes_required_fields(self) -> None:
        """to_dict() produces all required provenance fields."""
        tagger = ProvenanceTagger()
        prov = tagger.tag_oiw_example()
        d = prov.to_dict()
        for field_name in REQUIRED_PROVENANCE_FIELDS:
            assert field_name in d, f"missing required field: {field_name}"


class TestProvenanceAudit:
    def test_audit_passes_for_generated_sessions(self, tmp_path: Path) -> None:
        """10 generated learning sessions all pass provenance audit."""
        # Generate sessions in tmp_path
        run_learning_sessions(output_dir=tmp_path / "sessions")
        # Generate avoid patterns
        populate_negative_knowledge(tmp_path / "neg.yaml")

        result = verify_provenance(
            learning_sessions_dir=tmp_path / "sessions",
            avoid_patterns_yaml=tmp_path / "neg.yaml",
        )

        assert result.total_artifacts == 22  # 10 sessions + 12 avoid patterns
        assert result.with_provenance == 22
        assert result.missing_provenance == 0
        assert result.missing_fields == []
        assert result.real_count == 22
        assert result.by_source.get("learning-session") == 10
        assert result.by_source.get("failure-modes-catalog") == 12

    def test_audit_detects_missing_fields(self, tmp_path: Path) -> None:
        """Audit flags sessions missing required fields."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir(parents=True)
        # Write a session with no provenance
        bad_session = sessions_dir / "session-bad.yaml"
        bad_session.write_text(
            yaml.safe_dump(
                {
                    "id": "session-bad",
                    "requirement": "test",
                    "status": "VERIFIED",
                    # NO provenance field
                }
            )
        )

        result = verify_provenance(
            learning_sessions_dir=sessions_dir,
            avoid_patterns_yaml=tmp_path / "nonexistent.yaml",
        )

        assert result.total_artifacts == 1
        assert result.missing_provenance == 1
        assert len(result.missing_fields) == 1
        assert "source" in result.missing_fields[0]["missing"]
        assert "reviewer" in result.missing_fields[0]["missing"]

    def test_audit_distinguishes_real_vs_synthetic(self, tmp_path: Path) -> None:
        """Real and synthetic sources are counted separately."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir(parents=True)

        # Real artifact
        (sessions_dir / "session-real.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": "session-real",
                    "provenance": {
                        "source": "learning-session",
                        "reviewer": "x",
                        "license": "Apache-2.0",
                        "isReal": True,
                    },
                }
            )
        )
        # Synthetic artifact
        (sessions_dir / "session-synthetic.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": "session-synthetic",
                    "provenance": {
                        "source": "synthetic",
                        "reviewer": "auto",
                        "license": "Apache-2.0",
                        "isReal": False,
                    },
                }
            )
        )

        result = verify_provenance(
            learning_sessions_dir=sessions_dir,
            avoid_patterns_yaml=tmp_path / "nonexistent.yaml",
        )

        assert result.real_count == 1
        assert result.synthetic_count == 1
        assert result.by_source.get("learning-session") == 1
        assert result.by_source.get("synthetic") == 1
