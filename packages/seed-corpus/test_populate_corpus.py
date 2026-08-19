"""Tests for seed corpus population (WP-06 Sprint: 50+ trajectories).

Verifies the full pipeline: populate → synthesize → promote → retrieve.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from populate_corpus import generate_variation_artifacts, populate_corpus


class TestPopulateCorpus:
    def test_generate_variation_artifacts(self, tmp_path: Path) -> None:
        """38 variation artifacts are created."""
        dirs = generate_variation_artifacts(tmp_path / "variations")
        assert len(dirs) == 38
        for d in dirs:
            assert (d / "flow.yaml").is_file()
            assert (d / "tests" / "happy-path.yaml").is_file()

    def test_populate_corpus_reaches_50(self, tmp_path: Path) -> None:
        """Full pipeline produces ≥ 50 trajectories."""
        summary = populate_corpus(output_dir=tmp_path / "artifacts")

        # At least 50 trajectories synthesized
        assert (
            summary["totalTrajectories"] >= 50
        ), f"expected ≥50 trajectories, got {summary['totalTrajectories']}"

        # All promoted to PROJECT_APPROVED
        assert (
            summary["promotedToApproved"] == summary["totalTrajectories"]
        ), f"not all promoted: {summary['promotedToApproved']}/{summary['totalTrajectories']}"

        # Breakdown
        assert summary["oiwExamples"] >= 2  # order-to-s4 + sftp-order-drop
        assert summary["syntheticOriginal"] == 10
        assert summary["syntheticVariations"] == 38

    def test_populated_corpus_has_diverse_adapters(self, tmp_path: Path) -> None:
        """The populated corpus has SOAP, OData, IDoc, and Mail artifacts."""
        import yaml
        from ingest import get_all_artifact_dirs

        populate_corpus(output_dir=tmp_path / "artifacts")
        dirs = get_all_artifact_dirs(tmp_path / "artifacts")

        adapter_types = set()
        for d in dirs:
            flow = yaml.safe_load((d / "flow.yaml").read_text())
            for node in flow.get("spec", {}).get("nodes", []):
                adapter_types.add(node.get("type", ""))

        assert "sender.soap" in adapter_types or "receiver.soap" in adapter_types
        assert "receiver.odata-v4" in adapter_types
        assert "receiver.idoc" in adapter_types
        assert "receiver.mail" in adapter_types
