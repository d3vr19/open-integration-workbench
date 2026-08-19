"""Tests for EMG report generator (WP-07 Track D-003)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from emg_report import generate_report, save_report
from negative_knowledge import populate_negative_knowledge
from run_learning_sessions import run_learning_sessions


class TestEmgReport:
    def test_report_has_required_sections(self, tmp_path: Path) -> None:
        """Report contains all required top-level sections."""
        # Set up: generate sessions + avoid patterns
        sessions_dir = tmp_path / "sessions"
        run_learning_sessions(output_dir=sessions_dir)
        populate_negative_knowledge(tmp_path / "neg.yaml")

        # Generate report using tmp_path as seed corpus dir
        # We need to mock the paths since emg_report uses hardcoded paths
        report = generate_report(seed_corpus_dir=tmp_path)

        # The report should have all sections
        assert "emgKnowledgeReport" in report
        r = report["emgKnowledgeReport"]
        assert "corpus" in r
        assert "insights" in r
        assert "coverage" in r
        assert "retrieval" in r
        assert "learning" in r

    def test_corpus_counts_are_consistent(self, tmp_path: Path) -> None:
        """Total trajectories = synthetic + real + learning sessions."""
        run_learning_sessions(output_dir=tmp_path / "sessions")
        populate_negative_knowledge(tmp_path / "neg.yaml")

        report = generate_report(seed_corpus_dir=tmp_path)
        c = report["emgKnowledgeReport"]["corpus"]
        assert c["totalTrajectories"] == (
            c["syntheticTrajectories"]
            + c["realTrajectories"]
            + c["learningSessionPairs"]
        )

    def test_insights_include_intra_and_cross_task(self, tmp_path: Path) -> None:
        """Insights section has intraTask + crossTask + avoidPatterns."""
        run_learning_sessions(output_dir=tmp_path / "learning-sessions")
        populate_negative_knowledge(tmp_path / "negative-knowledge.yaml")

        report = generate_report(seed_corpus_dir=tmp_path)
        i = report["emgKnowledgeReport"]["insights"]
        assert i["intraTaskCorrections"] >= 0
        assert i["crossTaskPatterns"] >= 15  # WP-07 acceptance
        assert i["avoidPatterns"] >= 10

    def test_coverage_includes_all_dimensions(self, tmp_path: Path) -> None:
        """Coverage section has archetypes, failure modes, adapter families."""
        report = generate_report(seed_corpus_dir=tmp_path)
        c = report["emgKnowledgeReport"]["coverage"]
        assert c["archetypesCovered"] >= 5
        assert c["failureModesCovered"] >= 10
        assert c["adapterFamiliesCovered"] >= 5

    def test_retrieval_stats_in_valid_range(self, tmp_path: Path) -> None:
        """Retrieval stats are in [0.0, 1.0]."""
        report = generate_report(seed_corpus_dir=tmp_path)
        r = report["emgKnowledgeReport"]["retrieval"]
        assert 0.0 <= r["hitRate"] <= 1.0
        assert 0.0 <= r["averageConfidence"] <= 1.0
        assert 0.0 <= r["mechanicsFirstRate"] <= 1.0
        # WP-07 acceptance: mechanics-first rate ≥ 60%
        assert r["mechanicsFirstRate"] >= 0.60

    def test_save_report_writes_yaml(self, tmp_path: Path) -> None:
        """save_report creates a valid YAML file."""
        out = save_report(output_path=tmp_path / "report.yaml")
        assert out.is_file()
        doc = yaml.safe_load(out.read_text())
        assert "emgKnowledgeReport" in doc

    def test_report_with_real_data(self, tmp_path: Path) -> None:
        """End-to-end: generate sessions → avoid patterns → report."""
        # 1. Generate 10 learning sessions in the expected subdirectory
        run_learning_sessions(output_dir=tmp_path / "learning-sessions")
        # 2. Generate avoid patterns in the expected file
        populate_negative_knowledge(tmp_path / "negative-knowledge.yaml")
        # 3. Generate report (looks at tmp_path/learning-sessions/ and tmp_path/negative-knowledge.yaml)
        report = generate_report(seed_corpus_dir=tmp_path)

        r = report["emgKnowledgeReport"]
        assert r["corpus"]["learningSessionPairs"] == 10
        assert r["insights"]["avoidPatterns"] == 12
        assert r["learning"]["correctionsRetrieved"] == "10/10"
        assert r["learning"]["falsePositives"] == 0
