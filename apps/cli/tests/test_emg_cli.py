"""Tests for oiw emg CLI commands (WP-07 Track D-003 + E-001)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from click.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.cli import main  # noqa: E402


class TestEmgReportCommand:
    def test_emg_report_generates_yaml(self, tmp_path: Path) -> None:
        """`oiw emg report --output X.yaml` creates a YAML file."""
        runner = CliRunner()
        out = tmp_path / "report.yaml"
        result = runner.invoke(main, ["emg", "report", "--output", str(out)])
        assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"
        assert out.is_file()

        doc = yaml.safe_load(out.read_text())
        assert "emgKnowledgeReport" in doc
        r = doc["emgKnowledgeReport"]
        # All required sections present
        for section in ("corpus", "insights", "coverage", "retrieval", "learning"):
            assert section in r

    def test_emg_report_includes_corpus_counts(self, tmp_path: Path) -> None:
        """The report includes trajectory + insight counts."""
        runner = CliRunner()
        out = tmp_path / "report.yaml"
        runner.invoke(main, ["emg", "report", "--output", str(out)])

        doc = yaml.safe_load(out.read_text())
        c = doc["emgKnowledgeReport"]["corpus"]
        assert "totalTrajectories" in c
        assert "syntheticTrajectories" in c
        assert "realTrajectories" in c
        assert "learningSessionPairs" in c

    def test_emg_report_includes_retrieval_stats(self, tmp_path: Path) -> None:
        """Retrieval stats are in valid range [0, 1]."""
        runner = CliRunner()
        out = tmp_path / "report.yaml"
        runner.invoke(main, ["emg", "report", "--output", str(out)])

        doc = yaml.safe_load(out.read_text())
        r = doc["emgKnowledgeReport"]["retrieval"]
        assert 0.0 <= r["hitRate"] <= 1.0
        assert 0.0 <= r["averageConfidence"] <= 1.0
        assert 0.0 <= r["mechanicsFirstRate"] <= 1.0
        # WP-07 acceptance: ≥ 60%
        assert r["mechanicsFirstRate"] >= 0.60


class TestEmgProvenanceCommand:
    def test_emg_provenance_audits_existing_data(self, tmp_path: Path) -> None:
        """`oiw emg provenance` audits the seed corpus."""
        # Generate learning sessions + avoid patterns first
        sys.path.insert(0, str(REPO_ROOT / "packages" / "seed-corpus"))
        from negative_knowledge import populate_negative_knowledge  # noqa: E402
        from run_learning_sessions import run_learning_sessions  # noqa: E402

        seed_dir = tmp_path / "seed"
        (seed_dir / "learning-sessions").mkdir(parents=True)
        run_learning_sessions(output_dir=seed_dir / "learning-sessions")
        populate_negative_knowledge(seed_dir / "negative-knowledge.yaml")

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["emg", "provenance", "--seed-corpus-dir", str(seed_dir)],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert "Total artifacts:" in result.output
        assert "With provenance:" in result.output
        assert "Missing provenance:" in result.output

    def test_emg_provenance_reports_zero_for_empty_dir(self, tmp_path: Path) -> None:
        """With no data, audit reports 0 artifacts."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["emg", "provenance", "--seed-corpus-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "Total artifacts:   0" in result.output


class TestEmgGroup:
    def test_emg_help_lists_subcommands(self) -> None:
        """`oiw emg --help` lists report + provenance."""
        runner = CliRunner()
        result = runner.invoke(main, ["emg", "--help"])
        assert result.exit_code == 0
        assert "report" in result.output
        assert "provenance" in result.output
