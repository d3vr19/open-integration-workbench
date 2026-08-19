"""Tests for blog-post patterns + real ingestion (WP-07 Track A)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from blog_patterns import create_blog_post_patterns


class TestBlogPatterns:
    def test_create_all_blog_patterns(self, tmp_path: Path) -> None:
        """10 blog-post patterns created."""
        dirs = create_blog_post_patterns(tmp_path / "blog")
        assert len(dirs) == 10
        for d in dirs:
            assert (d / "flow.yaml").is_file()
            assert (d / "tests" / "happy-path.yaml").is_file()

    def test_blog_patterns_cover_5_plus_archetypes(self, tmp_path: Path) -> None:
        """Blog patterns cover at least 5 different archetypes."""
        dirs = create_blog_post_patterns(tmp_path / "blog")
        archetypes = set()
        for d in dirs:
            flow = yaml.safe_load((d / "flow.yaml").read_text())
            arch = flow.get("metadata", {}).get("labels", {}).get("archetype", "")
            if arch:
                archetypes.add(arch)
        assert len(archetypes) >= 5

    def test_blog_patterns_have_valid_ir(self, tmp_path: Path) -> None:
        """Each blog pattern has valid IR structure."""
        dirs = create_blog_post_patterns(tmp_path / "blog")
        for d in dirs:
            flow = yaml.safe_load((d / "flow.yaml").read_text())
            assert flow["apiVersion"] == "oiw.dev/v1alpha1"
            assert len(flow["spec"]["nodes"]) >= 2

    def test_blog_patterns_tagged_with_source(self, tmp_path: Path) -> None:
        """Each blog pattern has source=blog-post in labels."""
        dirs = create_blog_post_patterns(tmp_path / "blog")
        for d in dirs:
            flow = yaml.safe_load((d / "flow.yaml").read_text())
            assert flow["metadata"]["labels"]["source"] == "blog-post"

    def test_blog_patterns_can_be_ingested(self, tmp_path: Path) -> None:
        """Blog patterns can be ingested through the pipeline."""
        from ingest import ingest_artifact

        blog_dirs = create_blog_post_patterns(tmp_path / "blog")
        for d in blog_dirs:
            result = ingest_artifact(
                source_dir=d,
                artifact_id=d.name,
                output_dir=tmp_path / "artifacts",
                source="blog-post",
            )
            assert result.ingested
            assert result.node_count > 0
