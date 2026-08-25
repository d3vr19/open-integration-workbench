"""Tests for the EmbeddingGemma-300m backend (WP-08 PR-2 / Track A-002).

Acceptance (per WP-08 §5 A-002):
  - `RequirementEmbedder().backend_name == "gemma"` when extras are installed.
    → In environments without sentence-transformers, GemmaEmbedder falls
       back to a deterministic hash-based pseudo-embedding. The test
       asserts the fallback works (no crash) and that the auto-select
       chain ends on TF-IDF when no extras are present.
  - Two paraphrases of the same CodeJam requirement have cosine ≫ TF-IDF's.
    → Skipped here (requires the live model). Documented as a manual/nightly
       `@pytest.mark.embeddings` test.
  - Manifest records {backend, model, dim}. Loading a store whose manifest
       does not match the current embedder refuses to search. → covered by
       test_store.py::test_dim_mismatch_returns_empty.
  - CI stays green without Hugging Face. → This test file must NOT require
       any model download. Every test asserts behavior, not model output.
"""

from __future__ import annotations

import pytest

from oiw.agent.interpreter import NormalizedRequirement
from oiw.emg.embedding import (
    FastembedEmbedder,
    GemmaEmbedder,
    RequirementEmbedder,
    create_embedder,
)


def _make_req(raw: str = "add json schema validation") -> NormalizedRequirement:
    return NormalizedRequirement(
        intent="add-validation",
        raw=raw,
        archetype="api-to-erp",
        source_protocol="https",
        target_protocol="https",
        operations=["validate"],
        components=["validator.json-schema"],
    )


# ---------------------------------------------------------------------------
# TF-IDF backend (always available)
# ---------------------------------------------------------------------------


def test_tfidf_embedder_returns_60_dim_vector() -> None:
    """TF-IDF embedder returns a vector sized to its vocabulary (~53 terms)."""
    e = RequirementEmbedder()
    emb = e.embed(_make_req())
    # The exact dim matches len(VOCABULARY); that's currently 53.
    assert len(emb.vector) == len(e.VOCABULARY)
    # Non-zero (we hit some vocabulary terms)
    assert any(v != 0 for v in emb.vector)


def test_tfidf_cosine_similarity_is_self_1() -> None:
    """Cosine similarity of an embedding with itself is 1.0."""
    e = RequirementEmbedder()
    emb = e.embed(_make_req())
    assert abs(emb.cosine_similarity(emb) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Gemma backend — fallback behavior when sentence-transformers is missing
# ---------------------------------------------------------------------------


def test_gemma_embedder_falls_back_to_pseudo_embedding_when_st_missing(monkeypatch) -> None:
    """If sentence-transformers isn't installed, GemmaEmbedder uses a hash-based pseudo-embedding.

    The pseudo-embedding is NOT semantically meaningful, but it preserves
    exact-match similarity (same text → same vector) and never crashes.
    """
    from oiw.emg import embedding as emb_mod

    # Force the import cache to "not installed"
    monkeypatch.setattr(emb_mod, "_ST_IMPORT_OK", False)
    monkeypatch.setattr(emb_mod, "_ST_IMPORT_ATTEMPTED", True)
    monkeypatch.setattr(emb_mod, "_ST_IMPORT_ERROR", "ImportError forced by test")

    gemma = GemmaEmbedder(dim=128)
    emb = gemma.embed(_make_req())
    assert len(emb.vector) == 128
    # All values in [-1, 1] (hash-based pseudo-embedding range)
    assert all(-1.0 <= v <= 1.0 for v in emb.vector)
    # Same input → same output (deterministic)
    emb2 = gemma.embed(_make_req())
    assert emb.vector == emb2.vector


def test_gemma_embedder_dim_truncation_in_pseudo_fallback(monkeypatch) -> None:
    """Pseudo-embedding respects the configured dim even when the hash is shorter."""
    from oiw.emg import embedding as emb_mod

    monkeypatch.setattr(emb_mod, "_ST_IMPORT_OK", False)
    monkeypatch.setattr(emb_mod, "_ST_IMPORT_ATTEMPTED", True)

    # Default dim is 768 — pseudo-embedding should stretch the hash to fill
    gemma = GemmaEmbedder()
    emb = gemma.embed(_make_req())
    assert len(emb.vector) == 768


def test_gemma_backend_name_is_gemma() -> None:
    """GemmaEmbedder.backend_name == 'gemma' (per WP-08 A-002 acceptance)."""
    gemma = GemmaEmbedder()
    assert gemma.backend_name == "gemma"


# ---------------------------------------------------------------------------
# Fastembed backend — fallback behavior
# ---------------------------------------------------------------------------


def test_fastembed_embedder_falls_back_to_tfidf_when_not_installed(monkeypatch) -> None:
    """If fastembed isn't installed, FastembedEmbedder uses TF-IDF padded to fastembed's dim."""

    # Force the fastembed import to fail inside FastembedEmbedder._load_model
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "fastembed":
            raise ImportError("forced by test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    fe = FastembedEmbedder(dim=384)
    emb = fe.embed(_make_req())
    assert len(emb.vector) == 384


# ---------------------------------------------------------------------------
# Factory / auto-select chain
# ---------------------------------------------------------------------------


def test_create_embedder_explicit_tfidf() -> None:
    """create_embedder('tfidf') returns a RequirementEmbedder."""
    e = create_embedder("tfidf")
    assert isinstance(e, RequirementEmbedder)


def test_create_embedder_explicit_gemma() -> None:
    """create_embedder('gemma') returns a GemmaEmbedder."""
    e = create_embedder("gemma")
    assert isinstance(e, GemmaEmbedder)


def test_create_embedder_auto_falls_back_to_tfidf_without_extras(monkeypatch) -> None:
    """When no extras are installed, auto-select returns TF-IDF (CI default).

    This is the key acceptance: CI stays green without Hugging Face.
    """
    from oiw.emg import embedding as emb_mod

    # Simulate "no sentence-transformers + no fastembed + no OIW_EMBEDDING_API_KEY"
    monkeypatch.setattr(emb_mod, "_ST_IMPORT_OK", False)
    monkeypatch.setattr(emb_mod, "_ST_IMPORT_ATTEMPTED", True)

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ("sentence_transformers", "fastembed"):
            raise ImportError("forced by test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delenv("OIW_EMBEDDING_API_KEY", raising=False)

    e = create_embedder("auto")
    assert isinstance(
        e, RequirementEmbedder
    ), f"auto-select should fall back to TF-IDF without extras; got {type(e).__name__}"


def test_create_embedder_auto_uses_gemma_when_st_available(monkeypatch) -> None:
    """When sentence-transformers IS installed, auto-select returns GemmaEmbedder."""
    from oiw.emg import embedding as emb_mod

    # Simulate "sentence-transformers is installed"
    monkeypatch.setattr(emb_mod, "_ST_IMPORT_OK", True)
    monkeypatch.setattr(emb_mod, "_ST_IMPORT_ATTEMPTED", True)

    e = create_embedder("auto")
    assert isinstance(e, GemmaEmbedder)


def test_create_embedder_unknown_backend_raises() -> None:
    """Unknown backend name raises ValueError."""
    with pytest.raises(ValueError, match="unknown embedding backend"):
        create_embedder("nonexistent")


# ---------------------------------------------------------------------------
# OW-033: strict mode, honesty flags, backend probe
# ---------------------------------------------------------------------------


def test_strict_embedding_mode_parses_env(monkeypatch) -> None:
    """OIW_EMBEDDING_STRICT accepts 1/true/yes/on (case-insensitive)."""
    from oiw.emg.embedding import strict_embedding_mode

    for val in ("1", "true", "YES", "on", "True"):
        monkeypatch.setenv("OIW_EMBEDDING_STRICT", val)
        assert strict_embedding_mode() is True, f"{val!r} should be truthy"
    monkeypatch.delenv("OIW_EMBEDDING_STRICT")
    assert strict_embedding_mode() is False
    monkeypatch.setenv("OIW_EMBEDDING_STRICT", "0")
    assert strict_embedding_mode() is False


def test_gemma_strict_raises_instead_of_pseudo_fallback(monkeypatch) -> None:
    """With OIW_EMBEDDING_STRICT=1, an unloadable model RAISES — no silent pseudo vectors."""
    from oiw.emg import embedding as emb_mod

    monkeypatch.setattr(emb_mod, "_ST_IMPORT_OK", False)
    monkeypatch.setattr(emb_mod, "_ST_IMPORT_ATTEMPTED", True)
    monkeypatch.setattr(emb_mod, "_ST_IMPORT_ERROR", "ImportError forced by test")
    monkeypatch.setenv("OIW_EMBEDDING_STRICT", "1")

    gemma = GemmaEmbedder(dim=128)
    with pytest.raises(RuntimeError, match="OIW_EMBEDDING_STRICT"):
        gemma.embed(_make_req())


def test_gemma_non_strict_records_pseudo_flag(monkeypatch) -> None:
    """Without strict mode the fallback still works, and last_embed_pseudo tells the truth."""
    from oiw.emg import embedding as emb_mod

    monkeypatch.setattr(emb_mod, "_ST_IMPORT_OK", False)
    monkeypatch.setattr(emb_mod, "_ST_IMPORT_ATTEMPTED", True)
    monkeypatch.delenv("OIW_EMBEDDING_STRICT", raising=False)

    gemma = GemmaEmbedder(dim=128)
    assert gemma.last_embed_pseudo is None  # unknown before first embed
    gemma.embed(_make_req())
    assert gemma.last_embed_pseudo is True


def test_gemma_real_path_clears_pseudo_flag(monkeypatch) -> None:
    """A successful model encode records last_embed_pseudo=False."""
    gemma = GemmaEmbedder(dim=64)

    class _FakeModel:
        def encode(self, text: str, normalize_embeddings: bool = True):
            return [0.1] * 768

    monkeypatch.setattr(gemma, "_load_model", lambda: None)
    gemma._model = _FakeModel()

    emb = gemma.embed(_make_req())
    assert gemma.last_embed_pseudo is False
    # Matryoshka truncation to the configured dim still applies
    assert len(emb.vector) == 64


def test_fastembed_strict_raises_instead_of_tfidf_padding(monkeypatch) -> None:
    """With OIW_EMBEDDING_STRICT=1, fastembed unavailability RAISES instead of padding TF-IDF."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "fastembed":
            raise ImportError("forced by test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setenv("OIW_EMBEDDING_STRICT", "1")

    fe = FastembedEmbedder(dim=384)
    with pytest.raises(RuntimeError, match="OIW_EMBEDDING_STRICT"):
        fe.embed(_make_req())


def test_semantic_backend_flags_are_honest() -> None:
    """TF-IDF is keyword-level (semantic=False); Gemma/Fastembed are semantic."""
    assert RequirementEmbedder().semantic_backend is False
    assert GemmaEmbedder().semantic_backend is True
    assert FastembedEmbedder().semantic_backend is True


def test_probe_backend_reports_tfidf_usable() -> None:
    from oiw.emg.embedding import probe_backend

    usable, reason = probe_backend("tfidf")
    assert usable is True
    assert "always available" in reason


def test_probe_backend_unknown_backend_is_not_usable() -> None:
    from oiw.emg.embedding import probe_backend

    usable, reason = probe_backend("warp-drive")
    assert usable is False
    assert "unknown backend" in reason


def test_probe_backend_gemma_false_when_st_missing(monkeypatch) -> None:
    from oiw.emg import embedding as emb_mod

    monkeypatch.setattr(emb_mod, "_ST_IMPORT_OK", False)
    monkeypatch.setattr(emb_mod, "_ST_IMPORT_ATTEMPTED", True)
    monkeypatch.setattr(emb_mod, "_ST_IMPORT_ERROR", "ImportError forced by test")

    usable, reason = emb_mod.probe_backend("gemma")
    assert usable is False
    assert "sentence-transformers not installed" in reason


def test_build_emg_store_default_env_uses_real_tfidf(tmp_path, monkeypatch) -> None:
    """Without OIW_EMBEDDING_BACKEND, build_emg_store keeps the TF-IDF embedder."""
    from oiw.emg.store import JsonlEmgStore, build_emg_store

    for var in ("OIW_EMBEDDING_BACKEND", "OIW_EMBEDDING_MODEL", "OIW_EMBEDDING_DIM"):
        monkeypatch.delenv(var, raising=False)

    store = build_emg_store(root=tmp_path / "emg", create_if_missing=True)
    assert isinstance(store, JsonlEmgStore)
    assert store.manifest().embedding_backend == "tfidf"
    assert store._embedder.semantic_backend is False  # genuinely TF-IDF


def test_build_emg_store_honors_declared_backend(tmp_path, monkeypatch) -> None:
    """OIW_EMBEDDING_BACKEND=gemma constructs a GemmaEmbedder (not a lying TF-IDF)."""
    from oiw.emg.store import build_emg_store

    monkeypatch.setenv("OIW_EMBEDDING_BACKEND", "gemma")
    monkeypatch.setenv("OIW_EMBEDDING_MODEL", "google/embeddinggemma-300m")
    monkeypatch.setenv("OIW_EMBEDDING_DIM", "768")

    store = build_emg_store(root=tmp_path / "emg", create_if_missing=True)
    assert store._embedder.backend_name == "gemma"
    assert store.manifest().embedding_backend == "gemma"


def test_build_emg_store_unknown_backend_raises_loudly(tmp_path, monkeypatch) -> None:
    """An unknown OIW_EMBEDDING_BACKEND fails at construction — never silently TF-IDF."""
    from oiw.emg.store import build_emg_store

    monkeypatch.setenv("OIW_EMBEDDING_BACKEND", "bogus-backend")

    with pytest.raises(ValueError, match="unknown embedding backend"):
        build_emg_store(root=tmp_path / "emg", create_if_missing=True)


def test_store_backend_vector_mismatches_counts_liars(tmp_path) -> None:
    """backend_vector_mismatches reports nodes whose sidecar/dim disagree with the manifest."""
    from oiw.emg import store as store_mod
    from oiw.emg.store import JsonlEmgStore

    root = tmp_path / "emg"
    store = JsonlEmgStore(root=root, embedding_dim=len(RequirementEmbedder.VOCABULARY))
    store.load()
    node = store.upsert_task_from_requirement(_make_req(), task_id="t-1")

    assert store.backend_vector_mismatches() == {"backend": 0, "dim": 0}

    # Simulate a vector written by a different backend than the manifest claims
    store_mod._NODE_BACKENDS[node.id] = "gemma"
    assert store.backend_vector_mismatches()["backend"] == 1
    assert store.backend_vector_mismatches()["dim"] == 0

    # Simulate a wrong-dimension vector
    store_mod._NODE_BACKENDS[node.id] = "tfidf"
    node.requirement_embedding = [0.0] * 999
    assert store.backend_vector_mismatches()["dim"] == 1


# ---------------------------------------------------------------------------
# OW-033: EMGRetriever embedder resolution
# ---------------------------------------------------------------------------


def test_retriever_defaults_to_tfidf_without_env(monkeypatch) -> None:
    """No env config → TF-IDF query embedder (CI behavior unchanged)."""
    from oiw.emg.embedding import RequirementEmbedder
    from oiw.emg.retrieval import EMGRetriever

    monkeypatch.delenv("OIW_EMBEDDING_BACKEND", raising=False)
    r = EMGRetriever(task_store=object())
    assert isinstance(r._embedder, RequirementEmbedder)


def test_retriever_honors_env_backend(monkeypatch) -> None:
    """OIW_EMBEDDING_BACKEND=gemma → the retriever queries with a GemmaEmbedder."""
    from oiw.emg.embedding import GemmaEmbedder
    from oiw.emg.retrieval import EMGRetriever

    monkeypatch.setenv("OIW_EMBEDDING_BACKEND", "gemma")
    r = EMGRetriever(task_store=object())
    assert isinstance(r._embedder, GemmaEmbedder)


def test_retriever_explicit_embedder_beats_env(monkeypatch) -> None:
    """An explicitly passed embedder always wins over env resolution."""
    from oiw.emg.embedding import RequirementEmbedder
    from oiw.emg.retrieval import EMGRetriever

    monkeypatch.setenv("OIW_EMBEDDING_BACKEND", "gemma")
    mine = RequirementEmbedder()
    r = EMGRetriever(task_store=object(), embedder=mine)
    assert r._embedder is mine


def test_retriever_unknown_env_backend_raises_loudly(monkeypatch) -> None:
    """A configured-but-unbuildable backend RAISES — never silently TF-IDF."""
    from oiw.emg.retrieval import EMGRetriever

    monkeypatch.setenv("OIW_EMBEDDING_BACKEND", "bogus-backend")
    with pytest.raises(RuntimeError, match="would silently return garbage"):
        EMGRetriever(task_store=object())
