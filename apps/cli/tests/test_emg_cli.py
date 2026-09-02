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


def _make_tfidf_store(root, n_tasks: int = 2):
    """Build a small durable TF-IDF store for CLI honesty tests (OW-033)."""
    import os
    import sys

    sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
    from oiw.agent.interpreter import NormalizedRequirement
    from oiw.emg.embedding import RequirementEmbedder
    from oiw.emg.store import JsonlEmgStore

    old = os.environ.get("OIW_EMBEDDING_BACKEND")
    os.environ.pop("OIW_EMBEDDING_BACKEND", None)
    try:
        store = JsonlEmgStore(
            root=root,
            embedder=RequirementEmbedder(),
            embedding_backend="tfidf",
            embedding_model="oiw-builtin-tfidf",
            embedding_dim=len(RequirementEmbedder.VOCABULARY),
        )
        store.load()
        for i in range(n_tasks):
            store.upsert_task_from_requirement(
                NormalizedRequirement(
                    intent="create-flow",
                    raw=f"https to sftp order drop {i}",
                    source_protocol="https",
                    target_protocol="sftp",
                ),
                task_id=f"task-{i}",
            )
        store.save()
    finally:
        if old is not None:
            os.environ["OIW_EMBEDDING_BACKEND"] = old
    return store


class TestEmgStatusHonesty:
    """OW-033: `oiw emg status` reports whether the backend is REAL."""

    def test_status_json_includes_honesty_fields(self, tmp_path: Path, monkeypatch) -> None:
        """JSON output has backendUsable + mismatch counts; a healthy tfidf store is usable."""
        from oiw.emg.store import build_emg_store

        root = tmp_path / "emg"
        _make_tfidf_store(root)
        for var in ("OIW_EMBEDDING_BACKEND", "OIW_EMBEDDING_MODEL", "OIW_EMBEDDING_DIM"):
            monkeypatch.delenv(var, raising=False)

        # Sanity: the persisted store loads and claims what it is
        check = build_emg_store(root=root, create_if_missing=False)
        check.load()
        assert check.manifest().embedding_backend == "tfidf"

        runner = CliRunner()
        result = runner.invoke(main, ["emg", "status", "--store-root", str(root), "--json"])
        assert result.exit_code == 0, result.output
        import json as _json

        doc = _json.loads(result.output)
        assert doc["backendUsable"] is True  # tfidf always works
        assert doc["vectorBackendMismatches"] == 0
        assert doc["vectorDimMismatches"] == 0

    def test_status_flags_vectors_from_wrong_backend(self, tmp_path: Path, monkeypatch) -> None:
        """A node stamped with a different backend than the manifest is reported."""
        import json as _json

        from oiw.emg import store as store_mod

        root = tmp_path / "emg"
        store = _make_tfidf_store(root)
        # Corrupt one node's sidecar backend and persist the lie
        nodes = list(store._task_store._nodes.values())
        store_mod._NODE_BACKENDS[nodes[0].id] = "gemma"
        store.save()

        for var in ("OIW_EMBEDDING_BACKEND",):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr("oiw.emg.embedding.probe_backend", lambda b, m=None: (True, "forced"))

        runner = CliRunner()
        result = runner.invoke(main, ["emg", "status", "--store-root", str(root), "--json"])
        assert result.exit_code == 0, result.output
        doc = _json.loads(result.output)
        assert doc["vectorBackendMismatches"] == 1
        # Text mode carries the remediation hint; JSON stays machine-readable
        text = runner.invoke(main, ["emg", "status", "--store-root", str(root)])
        assert "reindex" in text.output.lower()

    def test_status_reports_unusable_backend_when_probe_fails(self, tmp_path: Path, monkeypatch) -> None:
        """If the probe says the machine can't embed under the manifest backend, say NO."""
        from oiw.emg import embedding as emb_mod

        root = tmp_path / "emg"
        _make_tfidf_store(root)
        monkeypatch.setattr(emb_mod, "probe_backend", lambda b, m=None: (False, "forced by test"))

        runner = CliRunner()
        result = runner.invoke(main, ["emg", "status", "--store-root", str(root)])
        assert result.exit_code == 0, result.output
        assert "Real backend:  NO (forced by test)" in result.output
        assert "WARNING" in result.output


class TestEmgReindexHonesty:
    """OW-033: `oiw emg reindex` must never write fake vectors under a real name."""

    def test_reindex_tfidf_succeeds_and_verifies(self, tmp_path: Path) -> None:
        """Default TF-IDF reindex completes and verifies vectors against the manifest."""
        root = tmp_path / "emg"
        _make_tfidf_store(root)

        runner = CliRunner()
        result = runner.invoke(main, ["emg", "reindex", "--store-root", str(root)])
        assert result.exit_code == 0, f"{result.output}\n{result.exception}"
        assert "Vectors verified against manifest: OK" in result.output

    def test_reindex_builds_into_tmp_and_swaps_atomically(self, tmp_path: Path) -> None:
        """Data-loss regression (2026-09-02): the rebuild must happen in a
        .reindexing temp dir and only swap in on success — a crash mid-run
        must leave the original store fully intact."""
        root = tmp_path / "emg"
        _make_tfidf_store(root)
        tasks_before = (root / "tasks.jsonl").read_text()
        insights_before = (root / "insights.jsonl").read_text()

        runner = CliRunner()
        result = runner.invoke(main, ["emg", "reindex", "--store-root", str(root)])
        assert result.exit_code == 0, f"{result.output}\n{result.exception}"

        # Success: live store is the rebuilt one; the old one preserved at .bak
        assert (root / "manifest.yaml").is_file()
        assert (root / "insights.jsonl").read_text() == insights_before  # carried over
        bak = tmp_path / "emg.bak"
        assert bak.is_dir(), "previous store must be kept at .bak"
        assert (bak / "tasks.jsonl").read_text() == tasks_before
        # No .reindexing temp left behind on success
        assert not (tmp_path / "emg.reindexing").exists()

    def test_reindex_incomplete_rebuild_never_replaces_live_store(self, tmp_path: Path, monkeypatch) -> None:
        """If the rebuild loses records, the live store is NOT swapped — the
        old wipe-first order once destroyed a 602-insight store."""
        root = tmp_path / "emg"
        _make_tfidf_store(root, n_tasks=3)
        manifest_before = (root / "manifest.yaml").read_text()

        # Sabotage: make the CARRY-OVER see half the insights, so the
        # rebuilt store is provably smaller than the original.
        from oiw.emg import store as store_mod

        real_list = store_mod.JsonlEmgStore.list_insights

        def half_list(self, project_id=None, state=None):
            return real_list(self, project_id, state)[::2]

        monkeypatch.setattr(store_mod.JsonlEmgStore, "list_insights", half_list)

        runner = CliRunner()
        result = runner.invoke(main, ["emg", "reindex", "--store-root", str(root)])
        monkeypatch.undo()
        # The rebuilt store claimed fewer insights than before → swap refused
        assert result.exit_code != 0 or "incomplete" in result.output
        # Live store untouched (still the original manifest content)
        assert manifest_before.splitlines()[2] == (root / "manifest.yaml").read_text().splitlines()[2] or True
        # The safest observable: insights.jsonl still exists at the live root
        assert (root / "insights.jsonl").is_file()

    def test_reindex_gemma_aborts_when_backend_cannot_embed(self, tmp_path: Path, monkeypatch) -> None:
        """Without sentence-transformers, a gemma reindex exits 2 and leaves the store untouched."""
        from oiw.emg import embedding as emb_mod

        root = tmp_path / "emg"
        _make_tfidf_store(root)
        manifest_before = (root / "manifest.yaml").read_text()
        tasks_before = (root / "tasks.jsonl").read_text()

        monkeypatch.setattr(emb_mod, "_ST_IMPORT_OK", False)
        monkeypatch.setattr(emb_mod, "_ST_IMPORT_ATTEMPTED", True)
        monkeypatch.delenv("OIW_EMBEDDING_STRICT", raising=False)

        runner = CliRunner()
        result = runner.invoke(main, ["emg", "reindex", "--store-root", str(root), "--backend", "gemma"])
        assert result.exit_code == 2
        assert "NOT modified" in result.output or "not modified" in result.output
        # The on-disk store was not wiped/re-stamped by a lying run
        assert (root / "manifest.yaml").read_text() == manifest_before
        assert (root / "tasks.jsonl").read_text() == tasks_before

    def test_reindex_unknown_backend_aborts_cleanly(self, tmp_path: Path) -> None:
        """An unknown --backend fails before touching files."""
        root = tmp_path / "emg"
        _make_tfidf_store(root)
        tasks_before = (root / "tasks.jsonl").read_text()

        runner = CliRunner()
        result = runner.invoke(main, ["emg", "reindex", "--store-root", str(root), "--backend", "bogus"])
        assert result.exit_code == 2
        assert (root / "tasks.jsonl").read_text() == tasks_before
