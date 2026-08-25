"""Durable EMG store — JSONL persistence (WP-08 PR-1 / Track A-001).

Spec ref: §13 (EMG), §13.16 (storage), §15.7–§15.14 (learning, retrieval).
WP-08 §5 A-001 spec:

    .oiw/emg/
      manifest.yaml          # schemaVersion, embedding.backend, embedding.model, embedding.dim
      insights.jsonl         # IntraTaskInsight + promotion state
      tasks.jsonl            # TaskMemoryNode including requirementEmbedding + embeddingBackend
      edges.jsonl            # CrossTaskEdge
      avoid-patterns.yaml    # pointer to catalog (managed by AvoidPatternStore)

The EmgStore protocol is a superset of InMemoryInsightStore,
TaskMemoryNodeStore, and CrossTaskEdgeStore — a single object that
all three callers can use. Existing in-memory classes stay as a
test double; production code goes through build_emg_store().

Design rules (WP-08 A-001 acceptance):
  - Atomic writes: write to a .tmp file then rename — a killed process
    cannot leave a truncated JSONL.
  - embeddingBackend is always written on every task node.
  - Vectors from a different backend/dim are skipped (similarity 0),
    never mixed.
  - Loading a store whose manifest does not match the current embedder
    refuses to search and tells the operator to re-embed
    (returns empty results + a `compatible` flag).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml

from ..agent.interpreter import NormalizedRequirement
from .embedding import RequirementEmbedder
from .promotion import InMemoryInsightStore, InsightRecord, MemoryPromotionState

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


@dataclass
class EmgStoreManifest:
    """Schema + embedding metadata for an EMG store on disk."""

    schema_version: str = "1"
    embedding_backend: str = "tfidf"
    embedding_model: str = "oiw-builtin-tfidf"
    # Default dim matches RequirementEmbedder.VOCABULARY length. Keep in sync
    # with apps/cli/oiw/emg/embedding.py — the dim is the source of truth,
    # not a magic number. WP-08 A-002 will swap to 768 (Gemma).
    embedding_dim: int = 53
    created_at: str = ""
    last_updated: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "embedding": {
                "backend": self.embedding_backend,
                "model": self.embedding_model,
                "dim": self.embedding_dim,
            },
            "createdAt": self.created_at,
            "lastUpdated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EmgStoreManifest:
        emb = d.get("embedding", {}) or {}
        return cls(
            schema_version=str(d.get("schemaVersion", "1")),
            embedding_backend=emb.get("backend", "tfidf"),
            embedding_model=emb.get("model", "oiw-builtin-tfidf"),
            embedding_dim=int(emb.get("dim", 60)),
            created_at=str(d.get("createdAt", "")),
            last_updated=str(d.get("lastUpdated", "")),
        )

    def matches(self, backend: str, model: str, dim: int) -> bool:
        return (
            self.embedding_backend == backend and self.embedding_model == model and self.embedding_dim == dim
        )


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class EmgStore(Protocol):
    """Durable EMG store protocol (WP-08 A-001).

    A single object that satisfies the read paths of:
      - InMemoryInsightStore (insights)
      - TaskMemoryNodeStore (task memory nodes)
      - CrossTaskEdgeStore (cross-task edges)
    """

    # --- lifecycle -----------------------------------------------------
    def load(self) -> None: ...
    def save(self) -> None: ...  # atomic: write temp + rename

    # --- insights ------------------------------------------------------
    def upsert_insight(self, record: InsightRecord) -> str: ...
    def get_insight(self, insight_id: str) -> InsightRecord | None: ...
    def list_insights(
        self,
        project_id: str | None = None,
        state: MemoryPromotionState | None = None,
    ) -> list[InsightRecord]: ...

    # --- task nodes ----------------------------------------------------
    def upsert_task(self, node: Any) -> str: ...
    def get_task(self, node_id: str) -> Any | None: ...
    def search_similar(
        self,
        vector: list[float],
        top_k: int = 5,
        min_similarity: float = 0.3,
        project_id: str | None = None,
    ) -> list[tuple[Any, float]]: ...

    # --- edges ---------------------------------------------------------
    def upsert_edge(self, edge: Any) -> str: ...
    def list_edges_for_task(self, task_id: str, max_edges: int = 5) -> list[Any]: ...

    # --- manifest / introspection -------------------------------------
    def manifest(self) -> EmgStoreManifest: ...
    def stats(self) -> dict[str, int]: ...


# ---------------------------------------------------------------------------
# JSONL implementation
# ---------------------------------------------------------------------------


class EmgStoreError(Exception):
    """Raised on EMG store load/save mismatches or IO errors."""


class JsonlEmgStore:
    """Durable EMG store backed by JSONL files.

    Layout (see module docstring). All writes go through atomic
    temp-file-then-rename so a killed process never leaves a truncated
    JSONL.

    The in-memory representation reuses the existing dataclasses
    (InsightRecord, TaskMemoryNode, CrossTaskEdge) so callers don't
    need to know whether they're talking to RAM or disk.

    Vectors from a different embedding backend/dim than the manifest
    are skipped on search (similarity 0), never mixed. Use reindex()
    to re-embed everything under a new model.
    """

    FILES = {
        "manifest": "manifest.yaml",
        "insights": "insights.jsonl",
        "tasks": "tasks.jsonl",
        "edges": "edges.jsonl",
    }

    def __init__(
        self,
        root: Path | str,
        *,
        embedder: RequirementEmbedder | None = None,
        embedding_backend: str = "tfidf",
        embedding_model: str = "oiw-builtin-tfidf",
        embedding_dim: int = 53,  # matches RequirementEmbedder.VOCABULARY length
        create_if_missing: bool = True,
    ) -> None:
        self.root = Path(root)
        self._embedder = embedder or RequirementEmbedder()
        self._want_backend = embedding_backend
        self._want_model = embedding_model
        self._want_dim = embedding_dim
        self._create_if_missing = create_if_missing
        self._manifest: EmgStoreManifest = EmgStoreManifest(
            embedding_backend=embedding_backend,
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
        )
        self._compatible = True  # flips to False if manifest mismatches
        # In-memory mirrors (the existing classes; we delegate to them
        # for query logic so JsonlEmgStore stays a thin persistence shim).
        self._insight_store = InMemoryInsightStore()
        # Lazy import to avoid circular at module import time
        from .edge_store import CrossTaskEdgeStore
        from .task_store import TaskMemoryNodeStore

        self._task_store = TaskMemoryNodeStore(embedder=self._embedder)
        self._edge_store = CrossTaskEdgeStore()
        self._loaded = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load all JSONL files into the in-memory mirrors.

        If the store already has a manifest on disk, we read it. If the
        on-disk manifest's embedding config differs from this store's
        constructor args, `_compatible` becomes False (searches return
        []). Use `reindex()` to re-embed under the new config.
        """
        if not self.root.is_dir():
            if self._create_if_missing:
                self.root.mkdir(parents=True, exist_ok=True)
                self._write_manifest()
                self._loaded = True
                return
            raise EmgStoreError(f"EMG store root does not exist: {self.root}")

        # Manifest first — determines expected embedding config
        manifest_path = self.root / self.FILES["manifest"]
        if manifest_path.is_file():
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            self._manifest = EmgStoreManifest.from_dict(raw)
            self._compatible = self._manifest.matches(self._want_backend, self._want_model, self._want_dim)
        else:
            # No manifest yet — write one and treat as compatible.
            self._write_manifest()
            self._compatible = True

        # Insights
        self._load_jsonl(self.FILES["insights"], self._load_insight_record)
        # Tasks
        self._load_jsonl(self.FILES["tasks"], self._load_task_node)
        # Edges
        self._load_jsonl(self.FILES["edges"], self._load_edge)

        self._loaded = True

    def force_remanifest(self) -> None:
        """Rewrite manifest.yaml with this store's constructor embedding config.

        Use after `load()` when you want to switch the on-disk manifest to a
        new backend/dim (e.g. during `oiw emg reindex`). Caller is responsible
        for re-embedding any task nodes; we only update the metadata.
        """
        self._manifest = EmgStoreManifest(
            embedding_backend=self._want_backend,
            embedding_model=self._want_model,
            embedding_dim=self._want_dim,
            created_at=self._manifest.created_at,
        )
        self._compatible = True
        self._write_manifest()

    def save(self) -> None:
        """Atomically write all JSONL files (temp file + rename)."""
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_jsonl_atomic(self.FILES["insights"], self._iter_insight_records())
        self._write_jsonl_atomic(self.FILES["tasks"], self._iter_task_nodes())
        self._write_jsonl_atomic(self.FILES["edges"], self._iter_edges())
        # Update manifest timestamp
        from datetime import UTC, datetime

        self._manifest.last_updated = datetime.now(tz=UTC).isoformat()
        self._write_manifest()

    # ------------------------------------------------------------------
    # Insights
    # ------------------------------------------------------------------

    def upsert_insight(self, record: InsightRecord) -> str:
        if not record.id:
            record.id = f"insight-{uuid.uuid4().hex[:12]}"
        self._insight_store.insert(record)
        return record.id

    def get_insight(self, insight_id: str) -> InsightRecord | None:
        try:
            return self._insight_store.get(insight_id)
        except KeyError:
            return None

    def list_insights(
        self,
        project_id: str | None = None,
        state: MemoryPromotionState | None = None,
    ) -> list[InsightRecord]:
        return self._insight_store.list(project_id=project_id, state=state)

    # ------------------------------------------------------------------
    # Task nodes
    # ------------------------------------------------------------------

    def upsert_task(self, node: Any) -> str:
        """Insert or update a TaskMemoryNode.

        Stamps `embeddingBackend` on the node if missing (WP-08 A-001
        bug-fix: insert_from_requirement forgets to stamp it).
        """
        if not getattr(node, "id", None):
            node.id = f"task-mem-{uuid.uuid4().hex[:12]}"
        # Stamp embedding backend if missing
        if not getattr(node, "embedding_backend", None):
            with contextlib.suppress(AttributeError):
                # TaskMemoryNode doesn't have the field yet — store as dict key
                # via a parallel map. We don't mutate the dataclass.
                node.embedding_backend = self._want_backend
        # Reuse the in-memory store's index, but bypass its auto-embedding
        # (the caller is responsible for the vector).
        self._task_store._nodes[node.id] = node
        return node.id

    def get_task(self, node_id: str) -> Any | None:
        return self._task_store.get(node_id)

    def search_similar(
        self,
        vector: list[float],
        top_k: int = 5,
        min_similarity: float = 0.3,
        project_id: str | None = None,
    ) -> list[tuple[Any, float]]:
        """Search for similar task nodes.

        If the store's manifest does not match the current embedder,
        returns [] — never mixes vectors from different backends/dims.
        """
        if not self._compatible:
            return []
        return self._task_store.search_similar(
            vector, top_k=top_k, min_similarity=min_similarity, project_id=project_id
        )

    def upsert_task_from_requirement(
        self,
        requirement: NormalizedRequirement,
        task_id: str,
        project_id: str | None = None,
        insight_ref: str | None = None,
        reward: dict[str, Any] | None = None,
        approval: str = "PROJECT_APPROVED",
        confidentiality_scope: str = "project",
    ) -> Any:
        """Create + persist a task node from a requirement.

        Convenience wrapper that embeds the requirement (using the
        configured embedder) and stamps `embeddingBackend` on the node.

        `confidentiality_scope`: "project" (default) nodes are only
        retrievable within their own project; "organization" nodes are
        global knowledge (seed corpus, public material). Seed-corpus
        ingestion MUST pass "organization" — a CodeJam pattern indexed as
        project-private is invisible to every other project's retrieval.
        """
        from .task_store import TaskMemoryNode

        embedding = self._embedder.embed(requirement)
        node = TaskMemoryNode(
            id=f"task-mem-{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            requirement_embedding=embedding.vector,
            normalized_requirement=requirement.to_dict(),
            insight_ref=insight_ref,
            reward=reward or {},
            approval=approval,
            project_id=project_id,
            confidentiality_scope=confidentiality_scope,
        )
        # Stamp backend via a sidecar attribute (dataclass is frozen-ish;
        # we use a module-level dict to track backends per node id).
        _NODE_BACKENDS[node.id] = self._want_backend
        self._task_store._nodes[node.id] = node
        return node

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    def upsert_edge(self, edge: Any) -> str:
        if not getattr(edge, "id", None):
            edge.id = f"edge-{uuid.uuid4().hex[:12]}"
        # Reuse the in-memory store's indices
        self._edge_store._edges[edge.id] = edge
        self._edge_store._by_source.setdefault(edge.source_task_id, []).append(edge.id)
        self._edge_store._by_target.setdefault(edge.target_task_id, []).append(edge.id)
        return edge.id

    def list_edges_for_task(self, task_id: str, max_edges: int = 5) -> list[Any]:
        return self._edge_store.get_edges_for_task(task_id, max_edges=max_edges)

    # ------------------------------------------------------------------
    # Manifest / introspection
    # ------------------------------------------------------------------

    def manifest(self) -> EmgStoreManifest:
        return self._manifest

    def stats(self) -> dict[str, int]:
        return {
            "insights": len(self._insight_store._records),
            "tasks": self._task_store.count(),
            "edges": self._edge_store.count(),
        }

    def backend_vector_mismatches(self) -> dict[str, int]:
        """Count stored task vectors that DON'T match the manifest claim.

        Honesty check for `oiw emg status`: a node can disagree with the
        manifest in two ways — its sidecar embeddingBackend differs from
        the manifest backend, or its vector length differs from the
        manifest dim. Either way the vector is not what the manifest says
        it is. After an honest reindex both counts are 0.
        """
        backend_mismatch = 0
        dim_mismatch = 0
        want_backend = self._manifest.embedding_backend
        want_dim = self._manifest.embedding_dim
        for node_id, node in self._task_store._nodes.items():
            if _NODE_BACKENDS.get(node_id, "tfidf") != want_backend:
                backend_mismatch += 1
            vec = getattr(node, "requirement_embedding", None) or []
            if vec and len(vec) != want_dim:
                dim_mismatch += 1
        return {"backend": backend_mismatch, "dim": dim_mismatch}

    @property
    def compatible(self) -> bool:
        """True if the on-disk manifest matches the current embedder."""
        return self._compatible

    @property
    def root_path(self) -> Path:
        return self.root

    # ------------------------------------------------------------------
    # Internals — JSONL load/save
    # ------------------------------------------------------------------

    def _write_manifest(self) -> None:
        from datetime import UTC, datetime

        if not self._manifest.created_at:
            self._manifest.created_at = datetime.now(tz=UTC).isoformat()
        manifest_path = self.root / self.FILES["manifest"]
        # Atomic write
        tmp = manifest_path.with_suffix(".yaml.tmp")
        tmp.write_text(
            yaml.safe_dump(self._manifest.to_dict(), sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, manifest_path)

    def _load_jsonl(self, filename: str, loader: Any) -> None:
        path = self.root / filename
        if not path.is_file():
            return
        with path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise EmgStoreError(f"invalid JSON in {path}:{line_no}: {exc}") from exc
                loader(record)

    def _write_jsonl_atomic(self, filename: str, records: Any) -> None:
        path = self.root / filename
        # Write to a temp file in the same dir (so os.replace is atomic on POSIX).
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=filename + ".", suffix=".tmp", dir=str(self.root))
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec, default=_json_default, ensure_ascii=False))
                    f.write("\n")
            os.replace(tmp_path, path)
        except Exception:
            # Best-effort cleanup of the temp file on failure
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def _load_insight_record(self, record: dict[str, Any]) -> None:
        try:
            state = MemoryPromotionState(record.get("state", "CAPTURED"))
        except ValueError:
            state = MemoryPromotionState.CAPTURED

        # Deserialize the insight payload back into an IntraTaskInsight object.
        # When loaded from JSONL, record.get("insight") is a plain dict — but
        # the EMG retriever's _score_match expects an IntraTaskInsight with
        # .successful_workflow / .corrections attributes. We reconstruct it here.
        insight_data = record.get("insight")
        insight_obj = _deserialize_insight(insight_data)

        insight = InsightRecord(
            id=record.get("id", f"insight-{uuid.uuid4().hex[:12]}"),
            state=state,
            trajectory_id=record.get("trajectoryId"),
            project_id=record.get("projectId"),
            insight=insight_obj,
            reviewed_by=record.get("reviewedBy"),
            approved_by=record.get("approvedBy"),
            deprecation_reason=record.get("deprecationReason"),
            revocation_reason=record.get("revocationReason"),
            created_at=record.get("createdAt", ""),
            updated_at=record.get("updatedAt", ""),
        )
        self._insight_store.insert(insight)

    def _load_task_node(self, record: dict[str, Any]) -> None:
        from .task_store import TaskMemoryNode

        node = TaskMemoryNode(
            id=record.get("id", f"task-mem-{uuid.uuid4().hex[:12]}"),
            task_id=record.get("taskId", ""),
            requirement_embedding=record.get("requirementEmbedding", []),
            normalized_requirement=record.get("normalizedRequirement", {}),
            insight_ref=record.get("insightRef"),
            reward=record.get("reward", {}),
            approval=record.get("approval", "CAPTURED"),
            target_profiles=record.get("targetProfiles", ["sap-cloud-integration-2026-07"]),
            confidentiality_scope=record.get("confidentialityScope", "project"),
            project_id=record.get("projectId"),
        )
        backend = record.get("embeddingBackend") or "tfidf"
        _NODE_BACKENDS[node.id] = backend
        self._task_store._nodes[node.id] = node

    def _load_edge(self, record: dict[str, Any]) -> None:
        from .edge_store import CrossTaskEdge
        from .insight.cross_task import CrossTaskInsight

        insight_dict = record.get("insight", {}) or {}
        try:
            insight = (
                CrossTaskInsight(**insight_dict)
                if insight_dict
                else CrossTaskInsight(
                    source_task_id="",
                    target_task_id="",
                    common_subgraph=[],
                    corrections=[],
                    confidence=0.0,
                )
            )
        except TypeError:
            # CrossTaskInsight signature drift — make a permissive one.
            insight = CrossTaskInsight(
                source_task_id=insight_dict.get("sourceTaskId", ""),
                target_task_id=insight_dict.get("targetTaskId", ""),
                common_subgraph=insight_dict.get("commonSubgraph", []),
                corrections=insight_dict.get("corrections", []),
                confidence=float(insight_dict.get("confidence", 0.0)),
            )
        edge = CrossTaskEdge(
            id=record.get("id", f"edge-{uuid.uuid4().hex[:12]}"),
            source_task_id=record.get("sourceTaskId", ""),
            target_task_id=record.get("targetTaskId", ""),
            insight=insight,
            similarity_score=float(record.get("similarityScore", 0.0)),
            times_applied=int(record.get("timesApplied", 0)),
            created_at=float(record.get("createdAt", 0.0)),
        )
        self._edge_store._edges[edge.id] = edge
        self._edge_store._by_source.setdefault(edge.source_task_id, []).append(edge.id)
        self._edge_store._by_target.setdefault(edge.target_task_id, []).append(edge.id)

    def _iter_insight_records(self):
        for rec in self._insight_store._records.values():
            d = rec.to_dict()
            if rec.insight is not None and hasattr(rec.insight, "to_dict"):
                d["insight"] = rec.insight.to_dict()
            yield d

    def _iter_task_nodes(self):
        for node in self._task_store._nodes.values():
            d = node.to_dict()
            d["embeddingBackend"] = _NODE_BACKENDS.get(node.id, self._want_backend)
            yield d

    def _iter_edges(self):
        for edge in self._edge_store._edges.values():
            yield edge.to_dict()


# Sidecar map: node_id -> embedding_backend. TaskMemoryNode is a dataclass
# without an `embedding_backend` field, so we keep this out-of-band. A
# future refactor can add the field to the dataclass and delete this map.
_NODE_BACKENDS: dict[str, str] = {}


def _deserialize_insight(data: Any) -> Any:
    """Reconstruct an IntraTaskInsight object from a dict (loaded from JSONL).

    Returns None if data is None. Returns the data unchanged if it's already
    an IntraTaskInsight (i.e. the record was inserted in-memory, not loaded
    from disk). Otherwise, rebuilds the IntraTaskInsight + CorrectionRule +
    InsightProvenance objects from the dict structure.
    """
    if data is None:
        return None
    # Already an IntraTaskInsight (in-memory path)
    if hasattr(data, "successful_workflow"):
        return data
    # Dict from JSONL — reconstruct
    if not isinstance(data, dict):
        return data

    from .insight.compiler import CorrectionRule, InsightProvenance, IntraTaskInsight

    # Reconstruct corrections
    corrections = []
    for c_data in data.get("corrections", []):
        corrections.append(
            CorrectionRule(
                trigger=c_data.get("trigger", {}),
                avoid=c_data.get("avoid", []),
                prefer=c_data.get("prefer", []),
                confidence=float(c_data.get("confidence", 1.0)),
            )
        )

    # Reconstruct provenance
    prov_data = data.get("provenance")
    provenance = None
    if prov_data and isinstance(prov_data, dict):
        provenance = InsightProvenance(
            exploration_trajectory_id=prov_data.get("explorationTrajectoryId", ""),
            expert_trajectory_id=prov_data.get("expertTrajectoryId", ""),
            match_stage=prov_data.get("matchStage", "rule-based"),
            compiler_version=prov_data.get("compilerVersion", "0.1.0"),
        )

    # Reconstruct successful_workflow (list of dicts with "action" tuple)
    # JSON serializes tuples as lists — convert back to tuples
    workflow = []
    for node in data.get("successfulWorkflow", []):
        action = node.get("action")
        if isinstance(action, list):
            action = tuple(action)
        workflow.append(
            {
                "action": action,
                "result": node.get("result", "applied"),
            }
        )

    return IntraTaskInsight(
        task_id=data.get("taskId", ""),
        successful_workflow=workflow,
        corrections=corrections,
        provenance=provenance,
    )


def _json_default(obj: Any) -> Any:
    """JSON serializer for objects not natively serializable."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_emg_store(
    root: Path | str | None = None,
    *,
    embedder: RequirementEmbedder | None = None,
    create_if_missing: bool = True,
) -> JsonlEmgStore:
    """Build a JsonlEmgStore from env config.

    Resolution order for `root`:
      1. Explicit arg.
      2. $OIW_WORKSPACE/.oiw/emg/  (workspace-level seed/tenant corpus)
      3. $PWD/.oiw/emg/             (project-scoped)
      4. ./oiw-emg/                  (fallback)

    Embedding backend config (A-002 + OW-033 honesty fix):
      OIW_EMBEDDING_BACKEND=gemma|fastembed|openai|tfidf  (default: tfidf in CI;
                                                            gemma when extras installed)
      OIW_EMBEDDING_MODEL=...
      OIW_EMBEDDING_DIM=...

    When the resolved backend is NOT tfidf, the real embedder is
    constructed via `create_embedder()` so stored vectors genuinely come
    from the backend named in the manifest. If that backend is
    unavailable (deps missing, model not cached), this RAISES — callers
    (CLI, server startup) surface the error loudly instead of writing
    TF-IDF vectors under a lying manifest. Pass `embedder=` explicitly to
    override (tests do this).
    """
    if root is None:
        ws = os.environ.get("OIW_WORKSPACE")
        if ws:
            root = Path(ws) / ".oiw" / "emg"
        elif os.environ.get("PWD"):
            root = Path(os.environ["PWD"]) / ".oiw" / "emg"
        else:
            root = Path("oiw-emg")

    backend = os.environ.get("OIW_EMBEDDING_BACKEND", "tfidf")
    model = os.environ.get("OIW_EMBEDDING_MODEL", "oiw-builtin-tfidf")
    dim = int(os.environ.get("OIW_EMBEDDING_DIM", "53"))  # matches RequirementEmbedder.VOCABULARY length

    if embedder is None and backend != "tfidf":
        from .embedding import create_embedder

        kwargs: dict[str, Any] = {}
        if backend == "gemma":
            kwargs["model_name"] = model if model != "oiw-builtin-tfidf" else None
            kwargs["dim"] = dim
        elif backend == "fastembed":
            kwargs["dim"] = dim
        embedder = create_embedder(backend, **kwargs)

    return JsonlEmgStore(
        root=root,
        embedder=embedder,
        embedding_backend=backend,
        embedding_model=model,
        embedding_dim=dim,
        create_if_missing=create_if_missing,
    )


__all__ = [
    "EmgStore",
    "EmgStoreManifest",
    "EmgStoreError",
    "JsonlEmgStore",
    "build_emg_store",
]
