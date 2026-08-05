"""Tests for D-002 retrieval accuracy (WP-07 Track D-002)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "seed-corpus"))

from tests.agent_eval.retrieval_accuracy import (  # noqa: E402
    PARAPHRASES,
    UNRELATED_REQUIREMENTS,
    run_d002_check,
    run_retrieval_accuracy_test,
)
from run_learning_sessions import run_learning_sessions  # noqa: E402


@pytest.fixture(scope="module")
def sessions_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate 30 sessions once for all tests in this module."""
    d = tmp_path_factory.mktemp("sessions")
    run_learning_sessions(output_dir=d, batches=(1, 2, 3))
    return d


@pytest.fixture(scope="module")
def accuracy_report(sessions_dir: Path) -> dict:
    """Run the retrieval accuracy test once."""
    return run_retrieval_accuracy_test(sessions_dir)


class TestRetrievalAccuracy:
    def test_runs_against_30_sessions(self, accuracy_report) -> None:
        """The test runs against all 30 learning sessions."""
        assert accuracy_report.total_sessions == 30

    def test_original_requirement_threshold(self, accuracy_report) -> None:
        """Acceptance: ≥ 25 of 30 corrections retrievable for original requirement."""
        assert (
            accuracy_report.original_retrieved_count >= 25
        ), f"only {accuracy_report.original_retrieved_count}/30 original retrieved"

    def test_paraphrased_requirement_threshold(self, accuracy_report) -> None:
        """Acceptance: ≥ 20 of 30 corrections retrievable for paraphrased requirement."""
        assert (
            accuracy_report.paraphrased_retrieved_count >= 20
        ), f"only {accuracy_report.paraphrased_retrieved_count}/30 paraphrased retrieved"

    def test_zero_false_positives(self, accuracy_report) -> None:
        """Acceptance: 0 false positives (no corrections for unrelated requirements)."""
        assert (
            accuracy_report.false_positive_count == 0
        ), f"{accuracy_report.false_positive_count} false positives detected"

    def test_each_session_has_result(self, accuracy_report) -> None:
        """Every session produced a result entry."""
        assert len(accuracy_report.results) == 30

    def test_original_confidence_above_threshold(self, accuracy_report) -> None:
        """Original retrievals have confidence > 0.3 (the retriever's threshold)."""
        for r in accuracy_report.results:
            if r.original_retrieved:
                assert (
                    r.original_confidence > 0.3
                ), f"{r.session_id}: confidence {r.original_confidence} below threshold"

    def test_paraphrases_cover_all_failure_modes(self) -> None:
        """PARAPHRASES dict has an entry for every failure mode fm-001..fm-012."""
        # Load the failure modes catalog
        catalog_path = REPO_ROOT / "packages" / "seed-corpus" / "failure-modes.yaml"
        catalog = yaml.safe_load(catalog_path.read_text())
        fm_ids = {fm["id"] for fm in catalog["spec"]["failureModes"]}

        paraphrase_keys = set(PARAPHRASES.keys())
        missing = fm_ids - paraphrase_keys
        assert not missing, f"missing paraphrases for: {missing}"

    def test_unrelated_requirements_are_diverse(self) -> None:
        """UNRELATED_REQUIREMENTS covers ≥ 5 different scenarios."""
        assert len(UNRELATED_REQUIREMENTS) >= 5
        # Each unrelated requirement mentions distinct components
        all_components = []
        for r in UNRELATED_REQUIREMENTS:
            all_components.extend(r["components"])
        # At least 8 distinct component keywords across all unrelated reqs
        distinct = set(all_components)
        assert (
            len(distinct) >= 8
        ), f"only {len(distinct)} distinct components in unrelated requirements"

    def test_save_report_yaml(self, sessions_dir: Path, tmp_path: Path) -> None:
        """The report saves as valid YAML."""
        run_d002_check(sessions_dir=sessions_dir, output_path=tmp_path / "report.yaml")
        assert (tmp_path / "report.yaml").is_file()
        doc = yaml.safe_load((tmp_path / "report.yaml").read_text())
        assert doc["kind"] == "RetrievalAccuracyReport"
        assert doc["spec"]["totalSessions"] == 30

    def test_end_to_end_passes_acceptance(
        self, sessions_dir: Path, tmp_path: Path
    ) -> None:
        """End-to-end: run_d002_check returns passed=True."""
        result = run_d002_check(
            sessions_dir=sessions_dir, output_path=tmp_path / "report.yaml"
        )
        assert result["passed"] is True
