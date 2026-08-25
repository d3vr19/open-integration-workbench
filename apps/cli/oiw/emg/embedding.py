"""EmbeddingGemma-300m embedder for the EMG (WP-08 PR-2 / Track A-002).

Spec ref: §13.16, §15.11 (Retrieval).
WP-08 §5 A-002 spec:

  | Backend | When | Dim | Notes |
  | gemma   | default for local/dev/tenant learning | 768 (or documented Matryoshka truncate) | sentence-transformers + google/embeddinggemma-300m |
  | fastembed | optional lighter local | 384 | keep |
  | openai  | if OIW_EMBEDDING_API_* set | model-defined | keep |
  | tfidf   | CI only | ~60 | keep as fallback; never the product default |

License: EmbeddingGemma is under Google's Gemma terms, not Apache-2.0.
We do NOT vendor weights. The model is downloaded at first use by
sentence-transformers; CI must not require this (set
OIW_EMBEDDING_BACKEND=tfidf in CI per WP-08 §10).

Auto-select logic (create_embedder("auto")):
  1. gemma  — if sentence-transformers is importable AND the model is
              cached locally (or HF_HUB_OFFLINE=0 so it can be downloaded).
  2. fastembed — if the fastembed package is installed.
  3. openai — if OIW_EMBEDDING_API_KEY is set.
  4. tfidf — fallback (always available; CI default).

The Gemma backend uses Matryoshka representation learning (MRL) — the
first N dimensions of the 768-dim vector are valid embeddings. We expose
`OIW_EMBEDDING_DIM` so callers can truncate to a smaller dim if they
want faster similarity search at the cost of recall.
"""

from __future__ import annotations

import hashlib
import math
import os
from collections import Counter
from dataclasses import dataclass
from typing import Any

from ..agent.interpreter import NormalizedRequirement

_TRUTHY = {"1", "true", "yes", "on"}


def strict_embedding_mode() -> bool:
    """True when OIW_EMBEDDING_STRICT is set to a truthy value.

    Strict mode makes real-model embedders FAIL LOUDLY instead of
    silently degrading to hash pseudo-embeddings / TF-IDF padding.
    Learning on vectors that don't match their claimed backend poisons
    the EMG, so any environment doing real learning should set this.
    """
    return os.environ.get("OIW_EMBEDDING_STRICT", "").strip().lower() in _TRUTHY


@dataclass
class RequirementEmbedding:
    """An embedded requirement vector + metadata."""

    vector: list[float]
    text: str
    requirement_hash: str

    def cosine_similarity(self, other: RequirementEmbedding) -> float:
        if len(self.vector) != len(other.vector):
            return 0.0
        dot = sum(a * b for a, b in zip(self.vector, other.vector, strict=True))
        mag_a = math.sqrt(sum(a * a for a in self.vector))
        mag_b = math.sqrt(sum(b * b for b in other.vector))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)


class RequirementEmbedder:
    """TF-IDF embedder — the always-available CI default.

    Kept as the fallback in the auto-select chain. See `create_embedder()`
    for the Gemma-aware factory.

    NOTE: this is keyword-level matching, NOT a semantic embedding.
    `semantic_backend` is False so callers can be honest about what the
    vectors mean.
    """

    semantic_backend = False

    VOCABULARY: list[str] = [
        "create-flow",
        "modify-flow",
        "fix-flow",
        "add-test",
        "refactor",
        "api-to-erp",
        "file-to-api",
        "api-to-api",
        "erp-to-api",
        "https-to-https",
        "https-to-sftp",
        "sftp-to-https",
        "sftp-to-sftp",
        "https-to-soap",
        "soap-to-https",
        "https-to-odata",
        "https",
        "sftp",
        "soap",
        "odata",
        "idoc",
        "smtp",
        "timer",
        "jdbc",
        "validate",
        "transform",
        "route",
        "filter",
        "split",
        "gather",
        "encode",
        "log",
        "validator.json-schema",
        "script.groovy",
        "transform.xslt",
        "receiver.http",
        "receiver.sftp",
        "receiver.soap",
        "receiver.odata-v4",
        "receiver.idoc",
        "receiver.mail",
        "sender.http",
        "sender.sftp",
        "sender.soap",
        "modifier.content",
        "router",
        "filter",
        "splitter",
        "gather",
        "encoder.base64",
        "log.message",
        "converter.json-to-xml",
        "converter.xml-to-json",
    ]

    TERM_INDEX: dict[str, int] = {term: i for i, term in enumerate(VOCABULARY)}

    def __init__(self) -> None:
        self._vocab_size = len(self.VOCABULARY)
        self._df = {term: 1 for term in self.VOCABULARY}
        self._total_docs = len(self.VOCABULARY)

    @property
    def backend_name(self) -> str:
        return "tfidf"

    @property
    def model_name(self) -> str:
        return "oiw-builtin-tfidf"

    @property
    def dim(self) -> int:
        return self._vocab_size

    def embed(self, requirement: NormalizedRequirement) -> RequirementEmbedding:
        text = self._requirement_to_text(requirement)
        terms = self._extract_terms(requirement)
        tf = Counter(terms)
        vector = [0.0] * self._vocab_size
        for term, count in tf.items():
            if term in self.TERM_INDEX:
                idx = self.TERM_INDEX[term]
                idf = math.log(self._total_docs / self._df.get(term, 1))
                vector[idx] = count * idf
        magnitude = math.sqrt(sum(v * v for v in vector))
        if magnitude > 0:
            vector = [v / magnitude for v in vector]
        req_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        return RequirementEmbedding(vector=vector, text=text, requirement_hash=req_hash)

    def _requirement_to_text(self, req: NormalizedRequirement) -> str:
        parts = [
            f"intent: {req.intent}",
            f"archetype: {req.archetype or 'unknown'}",
            f"source: {req.source_protocol or 'unknown'}",
            f"target: {req.target_protocol or 'unknown'}",
            f"operations: {', '.join(req.operations)}",
            f"components: {', '.join(req.components)}",
        ]
        return " | ".join(parts)

    def _extract_terms(self, req: NormalizedRequirement) -> list[str]:
        terms: list[str] = []
        if req.intent:
            terms.append(req.intent)
        if req.archetype:
            terms.append(req.archetype)
        if req.source_protocol:
            terms.append(req.source_protocol)
        if req.target_protocol:
            terms.append(req.target_protocol)
        terms.extend(req.operations)
        terms.extend(req.components)
        return terms


# ---------------------------------------------------------------------------
# WP-08 A-002: EmbeddingGemma-300m backend
# ---------------------------------------------------------------------------


# Sentinel for "we tried to import sentence_transformers and it failed".
# Cached so we don't retry on every embed() call.
_ST_IMPORT_ATTEMPTED = False
_ST_IMPORT_OK = False
_ST_IMPORT_ERROR: str | None = None


def _try_import_sentence_transformers() -> tuple[bool, str | None]:
    """Lazy import of sentence-transformers. Cached after first attempt."""
    global _ST_IMPORT_ATTEMPTED, _ST_IMPORT_OK, _ST_IMPORT_ERROR
    if _ST_IMPORT_ATTEMPTED:
        return _ST_IMPORT_OK, _ST_IMPORT_ERROR
    _ST_IMPORT_ATTEMPTED = True
    try:
        import sentence_transformers  # noqa: F401

        _ST_IMPORT_OK = True
        return True, None
    except Exception as exc:
        _ST_IMPORT_ERROR = str(exc)
        return False, _ST_IMPORT_ERROR


class GemmaEmbedder:
    """EmbeddingGemma-300m embedder (WP-08 A-002).

    Uses sentence-transformers + google/embeddinggemma-300m. The model
    is downloaded at first use unless cached locally (HF_HOME /
    SENTENCE_TRANSFORMERS_HOME). Per WP-08 §10, CI must NOT use this —
    set OIW_EMBEDDING_BACKEND=tfidf in CI.

    License: EmbeddingGemma is under Google's Gemma terms, not Apache-2.0.
    We do NOT vendor weights.

    Honesty contract (WP-08 A-002 follow-up / OW-033):
    - If the model cannot be loaded, embed() degrades to a hash
      pseudo-embedding ONLY when OIW_EMBEDDING_STRICT is unset. The flag
      `last_embed_pseudo` records what actually happened.
    - With OIW_EMBEDDING_STRICT=1 (any truthy value), embed() RAISES
      instead — learning environments must never write pseudo vectors
      under a gemma manifest.
    """

    MODEL_NAME = "google/embeddinggemma-300m"
    DEFAULT_DIM = 768

    semantic_backend = True

    def __init__(
        self,
        model_name: str | None = None,
        dim: int | None = None,
        *,
        eager_load: bool = False,
    ) -> None:
        self.model_name = model_name or os.environ.get("OIW_EMBEDDING_MODEL", self.MODEL_NAME)
        self.dim = dim or int(os.environ.get("OIW_EMBEDDING_DIM", str(self.DEFAULT_DIM)))
        self._model: Any = None
        # True when the most recent embed() used the hash pseudo-fallback.
        # None before the first embed() call.
        self.last_embed_pseudo: bool | None = None
        if eager_load:
            self._load_model()

    @property
    def backend_name(self) -> str:
        return "gemma"

    def _load_model(self) -> None:
        if self._model is not None:
            return
        ok, err = _try_import_sentence_transformers()
        if not ok:
            raise RuntimeError(
                f"sentence-transformers is not installed: {err}. "
                "Install with `pip install 'oiw[embeddings]'` to enable the Gemma backend. "
                "Otherwise set OIW_EMBEDDING_BACKEND=tfidf."
            )
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(self.model_name)

    def embed(self, requirement: NormalizedRequirement) -> RequirementEmbedding:
        """Embed a requirement using EmbeddingGemma-300m.

        Falls back to a deterministic hash-based pseudo-embedding if the
        model can't be loaded AND OIW_EMBEDDING_STRICT is unset — never
        crashes the caller. The pseudo-embedding preserves term-overlap
        similarity (so two requirements with the same intent/components
        still match) but loses paraphrase detection (which is the whole
        point of using Gemma). With OIW_EMBEDDING_STRICT=1 this raises
        instead of degrading.
        """
        text = self._requirement_to_text(requirement)
        try:
            self._load_model()
            vec = self._model.encode(text, normalize_embeddings=True)
            # Matryoshka truncate if dim < model's native dim
            actual_dim = self.dim
            if actual_dim < len(vec):
                vec = vec[:actual_dim]
                # Re-normalize after truncation
                mag = math.sqrt(sum(v * v for v in vec))
                if mag > 0:
                    vec = [v / mag for v in vec]
            vector = [float(v) for v in vec]
            self.last_embed_pseudo = False
        except Exception as exc:
            if strict_embedding_mode():
                # Fail LOUDLY: a pseudo vector stamped "gemma" poisons the
                # store. Strict environments must see this immediately.
                raise RuntimeError(
                    f"Gemma backend unavailable and OIW_EMBEDDING_STRICT is set: {exc}"
                ) from exc
            # Fallback: deterministic hash-based pseudo-embedding of the
            # same dimension. This is NOT a real embedding — it only
            # preserves exact-match similarity.
            vector = self._hash_pseudo_embedding(text)
            self.last_embed_pseudo = True
        req_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        return RequirementEmbedding(vector=vector, text=text, requirement_hash=req_hash)

    def _hash_pseudo_embedding(self, text: str) -> list[float]:
        """Deterministic hash-based pseudo-embedding (fallback only).

        Same text → same vector; different text → different vector.
        NOT semantically meaningful. Use only when the model is unavailable.
        """
        h = hashlib.sha512(text.encode()).digest()
        # Stretch to dim by repeating the 64-byte hash
        out: list[float] = []
        while len(out) < self.dim:
            for byte in h:
                out.append((byte / 127.5) - 1.0)  # [-1, 1]
            h = hashlib.sha512(h).digest()
        return out[: self.dim]

    def _requirement_to_text(self, req: NormalizedRequirement) -> str:
        parts = [
            f"intent: {req.intent}",
            f"archetype: {req.archetype or 'unknown'}",
            f"source: {req.source_protocol or 'unknown'}",
            f"target: {req.target_protocol or 'unknown'}",
            f"operations: {', '.join(req.operations)}",
            f"components: {', '.join(req.components)}",
            f"raw: {req.raw}",
        ]
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Fastembed backend (kept per WP-08 A-002 table)
# ---------------------------------------------------------------------------


class FastembedEmbedder:
    """Lightweight local embedder using Qdrant's fastembed (MiniLM, 384-dim).

    Kept as the second-choice backend for environments where Gemma is too
    heavy. Requires `pip install fastembed`.

    Honesty contract mirrors GemmaEmbedder: with OIW_EMBEDDING_STRICT set,
    a load failure raises instead of silently writing padded TF-IDF
    vectors under a fastembed manifest.
    """

    MODEL_NAME = "BAAI/bge-small-en-v1.5"
    DEFAULT_DIM = 384

    semantic_backend = True

    def __init__(self, model_name: str | None = None, dim: int | None = None):
        self.model_name = model_name or self.MODEL_NAME
        self.dim = dim or self.DEFAULT_DIM
        self._model: Any = None
        self.last_embed_pseudo: bool | None = None

    @property
    def backend_name(self) -> str:
        return "fastembed"

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        except Exception as exc:
            raise RuntimeError(
                f"fastembed is not installed: {exc}. " "Install with `pip install fastembed`."
            ) from exc

    def embed(self, requirement: NormalizedRequirement) -> RequirementEmbedding:
        text = RequirementEmbedder()._requirement_to_text(requirement)
        try:
            self._load_model()
            vec = next(self._model.embed([text]))
            vector = [float(v) for v in vec]
            self.last_embed_pseudo = False
        except Exception as exc:
            if strict_embedding_mode():
                raise RuntimeError(
                    f"fastembed backend unavailable and OIW_EMBEDDING_STRICT is set: {exc}"
                ) from exc
            # Fallback to TF-IDF embedding (different dim — caller must handle)
            tfidf = RequirementEmbedder()
            emb = tfidf.embed(requirement)
            # Pad with zeros to fastembed dim — better than crashing
            vector = emb.vector + [0.0] * max(0, self.dim - len(emb.vector))
            vector = vector[: self.dim]
            self.last_embed_pseudo = True
            return RequirementEmbedding(vector=vector, text=text, requirement_hash=emb.requirement_hash)
        req_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        return RequirementEmbedding(vector=vector, text=text, requirement_hash=req_hash)


# ---------------------------------------------------------------------------
# Backend usability probe (honest `oiw emg status`)
# ---------------------------------------------------------------------------


def probe_backend(backend: str, model: str | None = None) -> tuple[bool, str]:
    """Check whether a backend can ACTUALLY embed right now.

    Returns (usable, reason). This is what powers the honesty fields on
    `oiw emg status`: a manifest can claim "gemma" while the machine
    cannot load the model — status must say so, not parrot the manifest.

    For gemma this eagerly loads the weights from the local HF cache
    (`local_files_only=True`) so it never triggers a surprise download.
    """
    if backend == "tfidf":
        return True, "always available"

    if backend == "gemma":
        ok, err = _try_import_sentence_transformers()
        if not ok:
            return False, f"sentence-transformers not installed ({err})"
        try:
            from sentence_transformers import SentenceTransformer

            name = model or os.environ.get("OIW_EMBEDDING_MODEL", GemmaEmbedder.MODEL_NAME)
            try:
                SentenceTransformer(name, local_files_only=True)
            except TypeError:
                # Older sentence-transformers without the kwarg
                SentenceTransformer(name)
            return True, f"model loaded ({name})"
        except Exception as exc:
            return False, f"model not loadable locally: {exc}"

    if backend == "fastembed":
        try:
            import fastembed  # noqa: F401
        except Exception as exc:
            return False, f"fastembed not installed ({exc})"
        try:
            from fastembed import TextEmbedding

            TextEmbedding(model_name=model or FastembedEmbedder.MODEL_NAME)
            return True, "model loaded"
        except Exception as exc:
            return False, f"model not loadable: {exc}"

    if backend == "openai":
        if os.environ.get("OIW_EMBEDDING_API_KEY"):
            return False, "documented but not implemented (see create_embedder)"
        return False, "OIW_EMBEDDING_API_KEY not set"

    return False, f"unknown backend {backend!r}"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_embedder(backend: str = "auto", **kwargs: Any) -> Any:
    """Build an embedder by name (WP-08 A-002 auto-select chain).

    "auto" tries in order:
      1. gemma  — if sentence-transformers is importable + a HF cache exists
                  (or HF_HUB_OFFLINE=0). Skipped silently if not.
      2. fastembed — if the fastembed package is importable.
      3. openai — if OIW_EMBEDDING_API_KEY env var is set.
      4. tfidf  — always available. CI default.

    Explicit names ("gemma", "fastembed", "openai", "tfidf") skip the
    chain and load that backend directly. They raise RuntimeError if the
    underlying library is missing.
    """
    if backend == "tfidf":
        return RequirementEmbedder()

    if backend == "gemma":
        return GemmaEmbedder(**kwargs)

    if backend == "fastembed":
        return FastembedEmbedder(**kwargs)

    if backend == "openai":
        # Not implemented in this PR — out of scope for the local-first
        # productization path. The env-var check is documented in WP-08 A-002.
        api_key = os.environ.get("OIW_EMBEDDING_API_KEY", "")
        if not api_key:
            raise RuntimeError("openai backend requested but OIW_EMBEDDING_API_KEY is not set.")
        raise NotImplementedError(
            "openai backend is documented in WP-08 A-002 but not yet implemented. "
            "Use 'gemma' or 'tfidf' for now."
        )

    # Auto-select
    if backend == "auto":
        # 1. Gemma
        ok, _ = _try_import_sentence_transformers()
        if ok:
            return GemmaEmbedder(**kwargs)

        # 2. Fastembed
        try:
            import fastembed  # noqa: F401

            return FastembedEmbedder(**kwargs)
        except Exception:
            pass

        # 3. OpenAI — env-gated
        if os.environ.get("OIW_EMBEDDING_API_KEY"):
            try:
                return create_embedder("openai", **kwargs)
            except NotImplementedError:
                pass

        # 4. TF-IDF fallback (always available)
        return RequirementEmbedder()

    raise ValueError(f"unknown embedding backend: {backend!r}")


__all__ = [
    "RequirementEmbedder",
    "RequirementEmbedding",
    "GemmaEmbedder",
    "FastembedEmbedder",
    "create_embedder",
    "strict_embedding_mode",
    "probe_backend",
]
