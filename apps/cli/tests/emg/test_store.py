"""Tests for the durable JSONL EMG store (WP-08 PR-1 / Track A-001).

Acceptance (per WP-08 §5 A-001):
  - store.upsert_task(...); new JsonlEmgStore(path) in a second process;
    search_similar returns the same node.  → test_round_trip_persists_tasks
  - Atomic writes: a killed process cannot leave truncated JSONL.  → test_save_is_atomic
  - embeddingBackend is always written.                          → test_embedding_backend_stamped
  - Vectors from a different backend/dim are skipped (similarity 0).  → test_dim_mismatch_returns_empty
  - Existing in-memory tests still pass by injecting the RAM store.   → (covered by existing test suite)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from oiw.agent.interpreter import NormalizedRequirement
from oiw.emg.promotion import (
    InsightRecord,
    MemoryPromotionState,
)
from oiw.emg.store import (
    EmgStoreError,
    JsonlEmgStore,
    build_emg_store,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "emg"


@pytest.fixture()
def store(store_root: Path) -> JsonlEmgStore:
    s = JsonlEmgStore(root=store_root, embedding_dim=60)
    s.load()
    return s


def _make_requirement() -> NormalizedRequirement:
    return NormalizedRequirement(
        intent="add-validation",
        raw="add json schema validation to the order flow",
        archetype="api-to-erp",
        source_protocol="https",
        target_protocol="https",
        operations=["validate"],
        components=["validator.json-schema"],
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_load_creates_dir_if_missing(tmp_path: Path) -> None:
    """load() with create_if_missing=True creates the directory + manifest."""
    root = tmp_path / "does-not-exist-yet"
    s = JsonlEmgStore(root=root, embedding_dim=60)
    s.load()
    assert root.is_dir()
    assert (root / "manifest.yaml").is_file()


def test_load_raises_when_root_missing_and_no_create(tmp_path: Path) -> None:
    """load() with create_if_missing=False raises on missing root."""
    s = JsonlEmgStore(root=tmp_path / "missing", create_if_missing=False, embedding_dim=60)
    with pytest.raises(EmgStoreError, match="does not exist"):
        s.load()


def test_manifest_written_and_read(store_root: Path) -> None:
    """Manifest round-trips through load → save → load."""
    s1 = JsonlEmgStore(
        root=store_root,
        embedding_backend="gemma",
        embedding_model="google/embeddinggemma-300m",
        embedding_dim=768,
    )
    s1.load()
    s1.save()
    manifest_path = store_root / "manifest.yaml"
    assert manifest_path.is_file()
    raw = yaml.safe_load(manifest_path.read_text())
    assert raw["embedding"]["backend"] == "gemma"
    assert raw["embedding"]["model"] == "google/embeddinggemma-300m"
    assert raw["embedding"]["dim"] == 768

    s2 = JsonlEmgStore(root=store_root)
    s2.load()
    m = s2.manifest()
    assert m.embedding_backend == "gemma"
    assert m.embedding_model == "google/embeddinggemma-300m"
    assert m.embedding_dim == 768


# ---------------------------------------------------------------------------
# Insight persistence (WP-08 A-001)
# ---------------------------------------------------------------------------


def test_insight_round_trip(store_root: Path) -> None:
    """An insight upserted in one process is visible in another."""
    s1 = JsonlEmgStore(root=store_root, embedding_dim=60)
    s1.load()
    rec = InsightRecord(
        id="insight-test-001",
        state=MemoryPromotionState.PROJECT_APPROVED,
        trajectory_id="traj-001",
        project_id="order-to-s4",
    )
    s1.upsert_insight(rec)
    s1.save()

    # New store instance, same path — simulates a process restart
    s2 = JsonlEmgStore(root=store_root, embedding_dim=60)
    s2.load()
    loaded = s2.get_insight("insight-test-001")
    assert loaded is not None
    assert loaded.state == MemoryPromotionState.PROJECT_APPROVED
    assert loaded.trajectory_id == "traj-001"
    assert loaded.project_id == "order-to-s4"


def test_insight_list_filters_by_project(store: JsonlEmgStore) -> None:
    rec_a = InsightRecord(id="a", project_id="proj-a")
    rec_b = InsightRecord(id="b", project_id="proj-b")
    store.upsert_insight(rec_a)
    store.upsert_insight(rec_b)
    only_a = store.list_insights(project_id="proj-a")
    assert {r.id for r in only_a} == {"a"}


# ---------------------------------------------------------------------------
# Task node persistence (WP-08 A-001 acceptance)
# ---------------------------------------------------------------------------


def test_round_trip_persists_tasks(store_root: Path) -> None:
    """A task node upserted in process 1 is found by search_similar in process 2."""
    req = _make_requirement()
    s1 = JsonlEmgStore(root=store_root, embedding_dim=60)
    s1.load()
    s1.upsert_task_from_requirement(req, task_id="task-1", project_id="p1")
    s1.save()

    s2 = JsonlEmgStore(root=store_root, embedding_dim=60)
    s2.load()
    embed = s2._embedder.embed(req)
    # Project-scoped nodes require project_id to match (task_store.py:137-138)
    results = s2.search_similar(embed.vector, top_k=5, min_similarity=0.5, project_id="p1")
    assert len(results) >= 1
    assert results[0][0].task_id == "task-1"


def test_embedding_backend_stamped(store_root: Path) -> None:
    """embeddingBackend is always written to tasks.jsonl."""
    req = _make_requirement()
    s1 = JsonlEmgStore(
        root=store_root,
        embedding_backend="gemma",
        embedding_model="google/embeddinggemma-300m",
        embedding_dim=768,
    )
    s1.load()
    s1.upsert_task_from_requirement(req, task_id="t1", project_id="p1")
    s1.save()

    tasks_file = store_root / "tasks.jsonl"
    lines = [line for line in tasks_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["embeddingBackend"] == "gemma"


def test_save_is_atomic(store_root: Path) -> None:
    """save() writes via temp file + os.replace — no .tmp files left behind."""
    s1 = JsonlEmgStore(root=store_root, embedding_dim=60)
    s1.load()
    s1.upsert_insight(InsightRecord(id="i1", project_id="p"))
    s1.save()

    # No .tmp files should be left after save() succeeds
    leftover_tmps = list(store_root.glob("*.tmp"))
    assert leftover_tmps == [], f"temp files left behind: {leftover_tmps}"


def test_save_recovers_from_partial_write(store_root: Path) -> None:
    """If save() raises mid-write, the existing files are intact."""
    s1 = JsonlEmgStore(root=store_root, embedding_dim=60)
    s1.load()
    s1.upsert_insight(InsightRecord(id="keep-me", project_id="p"))
    s1.save()

    # Now simulate a failed write by patching os.replace to raise
    s1.upsert_insight(InsightRecord(id="new", project_id="p"))
    with (
        patch("oiw.emg.store.os.replace", side_effect=OSError("simulated failure")),
        pytest.raises(OSError),
    ):
        s1.save()

    # The original insights.jsonl should still contain only "keep-me"
    lines = [line for line in (store_root / "insights.jsonl").read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["id"] == "keep-me"


# ---------------------------------------------------------------------------
# Manifest mismatch protection (WP-08 A-001 acceptance)
# ---------------------------------------------------------------------------


def test_dim_mismatch_returns_empty(store_root: Path) -> None:
    """Vectors from a different dim are skipped (similarity 0), never mixed."""
    req = _make_requirement()
    s1 = JsonlEmgStore(root=store_root, embedding_dim=60, embedding_backend="tfidf")
    s1.load()
    s1.upsert_task_from_requirement(req, task_id="t1", project_id="p1")
    s1.save()

    # Open the store with a DIFFERENT backend/dim — search should return []
    s2 = JsonlEmgStore(
        root=store_root,
        embedding_dim=768,
        embedding_backend="gemma",
        embedding_model="google/embeddinggemma-300m",
    )
    s2.load()
    assert not s2.compatible
    results = s2.search_similar([0.0] * 60, top_k=5, min_similarity=0.0)
    assert results == [], "expected [] when manifest dims mismatch"


def test_stats_reports_counts(store: JsonlEmgStore) -> None:
    req = _make_requirement()
    store.upsert_insight(InsightRecord(id="i1", project_id="p"))
    store.upsert_task_from_requirement(req, task_id="t1", project_id="p")
    stats = store.stats()
    assert stats["insights"] == 1
    assert stats["tasks"] == 1
    assert stats["edges"] == 0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_build_emg_store_uses_workspace_env(tmp_path: Path, monkeypatch) -> None:
    """build_emg_store uses $OIW_WORKSPACE/.oiw/emg when set."""
    monkeypatch.setenv("OIW_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("PWD", raising=False)
    store = build_emg_store(create_if_missing=True)
    store.load()
    assert store.root == tmp_path / ".oiw" / "emg"
    assert (tmp_path / ".oiw" / "emg" / "manifest.yaml").is_file()


def test_build_emg_store_respects_embedding_env(tmp_path: Path, monkeypatch) -> None:
    """build_emg_store reads OIW_EMBEDDING_BACKEND/MODEL/DIM from env."""
    monkeypatch.setenv("OIW_EMBEDDING_BACKEND", "gemma")
    monkeypatch.setenv("OIW_EMBEDDING_MODEL", "google/embeddinggemma-300m")
    monkeypatch.setenv("OIW_EMBEDDING_DIM", "768")
    store = build_emg_store(root=tmp_path / "emg")
    assert store._want_backend == "gemma"
    assert store._want_model == "google/embeddinggemma-300m"
    assert store._want_dim == 768
