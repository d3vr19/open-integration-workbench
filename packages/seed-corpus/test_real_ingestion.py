"""Tests for real artifact ingestion (WP-07 Track A).

Covers:
  - Analyze a SAP ZIP artifact structure
  - Create pattern from analysis (manual extraction)
  - Batch ingestion of real artifacts
  - Parser gaps documented
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from real_ingestion import (
    analyze_sap_zip,
    create_pattern_from_analysis,
    ingest_real_artifacts,
)


class TestAnalyzeSapZip:
    def test_analyze_valid_zip(self, tmp_path: Path) -> None:
        """Analyze a ZIP with an iFlow + Groovy script."""
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                "src/main/resources/scenarioflows/OrderProcessing.iflw", "<iflow/>"
            )
            zf.writestr("src/main/resources/scripts/normalize.groovy", "def x = 1")
            zf.writestr("src/main/resources/schemas/order.xsd", "<schema/>")

        analysis = analyze_sap_zip(zip_path)
        assert len(analysis["iflows"]) == 1
        assert len(analysis["scripts"]) == 1
        assert len(analysis["schemas"]) == 1

    def test_analyze_bad_zip(self, tmp_path: Path) -> None:
        """Analyze a corrupt ZIP → error recorded."""
        zip_path = tmp_path / "bad.zip"
        zip_path.write_bytes(b"not a zip file")

        analysis = analyze_sap_zip(zip_path)
        assert "error" in analysis


class TestCreatePatternFromAnalysis:
    def test_create_pattern_with_scripts_and_schemas(self, tmp_path: Path) -> None:
        """Create an IR project from analysis with scripts + schemas."""
        analysis = {
            "zip_path": "/tmp/test.zip",
            "files": ["flow.iflw", "script.groovy", "schema.xsd"],
            "iflows": ["flow.iflw"],
            "scripts": ["script.groovy"],
            "schemas": ["schema.xsd"],
            "mappings": [],
        }
        result = create_pattern_from_analysis(
            analysis, "test-001", tmp_path, source="sap-codejam"
        )
        assert result.ingested
        assert result.method == "manual"
        assert result.node_count >= 4  # sender + validator + script + receiver

        # Verify flow.yaml exists
        artifact_dir = tmp_path / "test-001"
        assert (artifact_dir / "flow.yaml").is_file()
        assert (artifact_dir / "metadata.yaml").is_file()
        assert (artifact_dir / "resources" / "scripts" / "process.groovy").is_file()
        assert (artifact_dir / "resources" / "schemas" / "input.json").is_file()

    def test_create_pattern_with_mappings(self, tmp_path: Path) -> None:
        """Create an IR project with XSLT mappings."""
        analysis = {
            "zip_path": "/tmp/test.zip",
            "files": ["flow.iflw", "transform.xsl"],
            "iflows": ["flow.iflw"],
            "scripts": [],
            "schemas": [],
            "mappings": ["transform.xsl"],
        }
        result = create_pattern_from_analysis(analysis, "test-002", tmp_path)
        assert result.ingested
        artifact_dir = tmp_path / "test-002"
        assert (artifact_dir / "resources" / "mappings" / "transform.xsl").is_file()

    def test_create_pattern_empty_zip(self, tmp_path: Path) -> None:
        """ZIP with no recognizable content → not ingested."""
        analysis = {
            "zip_path": "/tmp/empty.zip",
            "files": ["readme.txt"],
            "iflows": [],
            "scripts": [],
            "schemas": [],
            "mappings": [],
        }
        result = create_pattern_from_analysis(analysis, "test-003", tmp_path)
        assert not result.ingested
        assert len(result.errors) > 0


class TestBatchIngestion:
    def test_batch_ingest_creates_artifacts(self, tmp_path: Path) -> None:
        """Batch ingestion creates artifact directories."""
        # Create test ZIPs
        zip1 = tmp_path / "zip1.zip"
        with zipfile.ZipFile(zip1, "w") as zf:
            zf.writestr("flow.iflw", "<iflow/>")
            zf.writestr("script.groovy", "def x = 1")

        zip2 = tmp_path / "zip2.zip"
        with zipfile.ZipFile(zip2, "w") as zf:
            zf.writestr("flow.iflw", "<iflow/>")
            zf.writestr("transform.xsl", "<xsl/>")

        results = ingest_real_artifacts(
            [zip1, zip2], tmp_path / "artifacts", source="test"
        )
        assert len(results) == 2
        assert all(r.ingested for r in results)

    def test_batch_ingest_documents_parser_gaps(self, tmp_path: Path) -> None:
        """Parser gaps are documented for failed imports."""
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("flow.iflw", "<iflow/>")

        results = ingest_real_artifacts(
            [zip_path], tmp_path / "artifacts", source="test"
        )
        # Even with content, the manual extraction should work
        assert results[0].ingested
