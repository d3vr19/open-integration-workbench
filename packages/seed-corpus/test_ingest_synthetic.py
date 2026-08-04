"""Tests for batch ingestion + synthetic artifacts (WP-06 Tasks A-002, B-007).

Covers:
  - Ingest OIW examples → artifacts created with IR + metadata
  - Ingest with missing flow.yaml → rejected
  - Batch ingest → multiple directories created
  - Synthetic artifact creation → 10 artifacts with adapters
  - Synthetic artifacts have correct adapter types
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingest import ingest_artifact, ingest_oiw_examples, get_all_artifact_dirs  # noqa: E402
from synthetic_artifacts import create_all_synthetic_artifacts  # noqa: E402


class TestBatchIngestion:
    def test_ingest_oiw_examples(self, tmp_path: Path) -> None:
        """Ingest OIW examples → artifacts created with IR + metadata."""
        results = ingest_oiw_examples(output_dir=tmp_path / "artifacts")
        assert len(results) >= 2  # order-to-s4 + sftp-order-drop
        for result in results:
            assert result.ingested
            assert result.flow_id is not None
            assert result.node_count > 0

            # Verify artifact directory exists
            artifact_dir = tmp_path / "artifacts" / result.artifact_id
            assert (artifact_dir / "flow.yaml").is_file()
            assert (artifact_dir / "metadata.yaml").is_file()

    def test_ingest_missing_flow_yaml(self, tmp_path: Path) -> None:
        """Ingest with missing flow.yaml → rejected with error."""
        source = tmp_path / "no-flow"
        source.mkdir()
        (source / "README.md").write_text("no flow here")

        result = ingest_artifact(
            source_dir=source,
            artifact_id="test-no-flow",
            output_dir=tmp_path / "artifacts",
        )
        assert not result.ingested
        assert any("flow.yaml not found" in e for e in result.errors)

    def test_ingest_copies_resources_and_tests(self, tmp_path: Path) -> None:
        """Ingest copies resources/ and tests/ directories."""
        source = tmp_path / "source"
        source.mkdir()
        (source / "flow.yaml").write_text(
            "apiVersion: oiw.dev/v1alpha1\nkind: IntegrationFlow\n"
            "metadata:\n  id: test\n  name: test\n  version: 1\n"
            "spec:\n  entrypoints: []\n  nodes: []\n  edges: []\n  extensions: {}\n"
        )
        resources = source / "resources" / "schemas"
        resources.mkdir(parents=True)
        (resources / "order.schema.json").write_text('{"type": "object"}')
        tests = source / "tests"
        tests.mkdir()
        (tests / "happy-path.yaml").write_text(
            "apiVersion: oiw.dev/v1alpha1\nkind: FlowTest\n"
        )

        result = ingest_artifact(
            source_dir=source,
            artifact_id="test-with-resources",
            output_dir=tmp_path / "artifacts",
        )
        assert result.ingested
        assert result.resource_count == 1
        assert result.test_count == 1

        artifact_dir = tmp_path / "artifacts" / "test-with-resources"
        assert (artifact_dir / "resources" / "schemas" / "order.schema.json").is_file()
        assert (artifact_dir / "tests" / "happy-path.yaml").is_file()

    def test_get_all_artifact_dirs(self, tmp_path: Path) -> None:
        """get_all_artifact_dirs lists ingested artifacts."""
        ingest_oiw_examples(output_dir=tmp_path / "artifacts")
        dirs = get_all_artifact_dirs(tmp_path / "artifacts")
        assert len(dirs) >= 2
        for d in dirs:
            assert (d / "flow.yaml").is_file()


class TestSyntheticArtifacts:
    def test_create_all_synthetic_artifacts(self, tmp_path: Path) -> None:
        """Create all 10 synthetic artifacts."""
        dirs = create_all_synthetic_artifacts(tmp_path / "synthetic")
        assert len(dirs) == 10
        for d in dirs:
            assert (d / "flow.yaml").is_file()
            assert (d / "diagram.json").is_file()
            assert (d / "tests" / "happy-path.yaml").is_file()

    def test_synthetic_artifacts_have_correct_adapter_types(
        self, tmp_path: Path
    ) -> None:
        """Each synthetic artifact uses a new adapter type."""
        dirs = create_all_synthetic_artifacts(tmp_path / "synthetic")

        adapter_types_found = set()
        for d in dirs:
            flow = yaml.safe_load((d / "flow.yaml").read_text())
            for node in flow.get("spec", {}).get("nodes", []):
                adapter_types_found.add(node.get("type", ""))

        # At least one of each new adapter
        assert (
            "sender.soap" in adapter_types_found
            or "receiver.soap" in adapter_types_found
        )
        assert "receiver.odata-v4" in adapter_types_found
        assert "receiver.idoc" in adapter_types_found
        assert "receiver.mail" in adapter_types_found

    def test_synthetic_artifacts_have_valid_ir(self, tmp_path: Path) -> None:
        """Synthetic artifacts have valid IR structure."""
        dirs = create_all_synthetic_artifacts(tmp_path / "synthetic")
        for d in dirs:
            flow = yaml.safe_load((d / "flow.yaml").read_text())
            assert flow["apiVersion"] == "oiw.dev/v1alpha1"
            assert flow["kind"] == "IntegrationFlow"
            assert "metadata" in flow
            assert "spec" in flow
            assert "nodes" in flow["spec"]
            assert len(flow["spec"]["nodes"]) > 0

    def test_synthetic_artifacts_can_be_ingested(self, tmp_path: Path) -> None:
        """Synthetic artifacts can be ingested through the pipeline."""
        synthetic_dirs = create_all_synthetic_artifacts(tmp_path / "synthetic")

        for d in synthetic_dirs:
            result = ingest_artifact(
                source_dir=d,
                artifact_id=d.name,
                output_dir=tmp_path / "artifacts",
                source="synthetic",
            )
            assert result.ingested
            assert result.node_count > 0
