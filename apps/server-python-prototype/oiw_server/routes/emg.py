"""EMG insight routes — expose EMG insights + stats to the UI.

WP-06 Track E Task E-003.
WP-08 PR-3 / Track A-003: routes now read from the persisted JsonlEmgStore
at {OIW_WORKSPACE}/.oiw/emg/ (or ./.oiw/emg/) instead of the test-only
process-global _INSIGHT_STORE dict.
Spec ref: §15.11 (Retrieval), §15.14 (Seed Corpus).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["EMG"])


class InsightSummary(BaseModel):
    id: str
    taskId: str
    confidence: float
    supportCount: int
    workflowStepCount: int
    correctionCount: int
    provenance: dict | None = None
    approval: str = "PROJECT_APPROVED"


class InsightDetail(BaseModel):
    id: str
    taskId: str
    successfulWorkflow: list[dict]
    corrections: list[dict]
    confidence: float
    supportCount: int
    provenance: dict | None = None


class EMGStats(BaseModel):
    totalTrajectories: int = 0
    approvedInsights: int = 0
    crossTaskEdges: int = 0
    retrievalHitRate: float = 0.0
    adapterFamilies: list[str] = []
    # WP-08 A-003: surface backend/model/dim so the UI can show the
    # store's actual embedding config, not a guess.
    embeddingBackend: str = ""
    embeddingModel: str = ""
    embeddingDim: int = 0
    storePath: str = ""
    compatible: bool = True


# In-memory store for the API (kept for test compatibility — tests that
# call populate_emg_api() with synthetic data still work). Production
# reads go through the JsonlEmgStore loaded at startup.
_INSIGHT_STORE: dict[str, dict] = {}
_STATS: dict[str, Any] = {}
# Lazily-loaded durable store. Set by `load_persisted_store()` on app startup.
_EMG_STORE: Any = None


def populate_emg_api(insights: list[dict], stats: dict | None = None) -> None:
    """Populate the in-memory EMG API store (test helper).

    Production code should NOT call this — it leaves _EMG_STORE untouched,
    so the persisted store still wins on reads. Tests that need a known
    set of insights should set `_EMG_STORE = None` after calling this to
    force the in-memory path.
    """
    global _STATS
    _INSIGHT_STORE.clear()
    for insight in insights:
        _INSIGHT_STORE[insight.get("id", "")] = insight
    if stats:
        _STATS = stats


def load_persisted_store(store_root: Path | str | None = None) -> Any | None:
    """Load the JsonlEmgStore from disk at app startup (WP-08 A-003).

    Idempotent: subsequent calls return the already-loaded store. Returns
    None (and logs) if the store cannot be loaded — the routes then fall
    back to the in-memory test store.

    Per WP-08 A-003: this is called from `oiw_server.main:create_app()` so
    every server process loads the same persisted corpus.
    """
    global _EMG_STORE
    if _EMG_STORE is not None:
        return _EMG_STORE

    # Resolve the workspace root. The CLI and the API server MUST use the
    # same path so a CLI-side `oiw emg reindex` is visible to the server
    # without a restart — for in-process reads. (Cross-process visibility
    # requires a restart today; that's documented in DEVELOPMENT_LOG.)
    if store_root is None:
        ws = os.environ.get("OIW_WORKSPACE")
        store_root = Path(ws) / ".oiw" / "emg" if ws else Path(".oiw") / "emg"

    try:
        # Import here so the server can boot even if apps/cli isn't installed
        # (some routes don't need EMG at all).
        import sys

        cli_src = Path(__file__).resolve().parents[4] / "apps" / "cli"
        if str(cli_src) not in sys.path:
            sys.path.insert(0, str(cli_src))
        from oiw.emg.store import build_emg_store  # type: ignore[import-not-found]

        store = build_emg_store(root=store_root, create_if_missing=True)
        store.load()
        _EMG_STORE = store
        return store
    except Exception as exc:  # pragma: no cover — defensive, logged at startup
        # Don't crash the server; the routes will fall back to the in-memory store.
        import logging

        logging.getLogger("oiw_server.emg").warning(
            "could not load persisted EMG store at %s: %s — falling back to in-memory test store",
            store_root,
            exc,
        )
        return None


def _read_store_or_memory() -> tuple[Any, bool]:
    """Return (store_or_None, used_durable_store).

    If a durable store is loaded, returns (store, True). Otherwise returns
    (the in-memory _INSIGHT_STORE dict, False) so legacy test paths work.
    """
    if _EMG_STORE is not None:
        return _EMG_STORE, True
    return _INSIGHT_STORE, False


@router.get("/projects/{project_id}/emg/insights", response_model=list[InsightSummary])
def list_emg_insights(project_id: str) -> list[InsightSummary]:
    """List all approved EMG insights for a project."""
    store, used_durable = _read_store_or_memory()
    results: list[InsightSummary] = []

    if used_durable:
        # Durable path: insights live as InsightRecord objects with optional
        # `insight` payload (an IntraTaskInsight) attached.
        for rec in store.list_insights(project_id=project_id):
            if rec.state.value != "PROJECT_APPROVED":
                continue
            insight = rec.insight
            workflow = getattr(insight, "successful_workflow", []) or []
            corrections = getattr(insight, "corrections", []) or []
            prov = getattr(insight, "provenance", None)
            if prov is not None and hasattr(prov, "to_dict"):
                prov = prov.to_dict()
            results.append(
                InsightSummary(
                    id=rec.id,
                    taskId=rec.trajectory_id or "",
                    confidence=float(getattr(insight, "confidence", 0.0) or 0.0),
                    supportCount=int(getattr(insight, "support_count", 0) or 0),
                    workflowStepCount=len(workflow),
                    correctionCount=len(corrections),
                    provenance=prov if isinstance(prov, dict) else None,
                )
            )
        return results

    # Legacy in-memory path (test compat)
    for insight in store.values():
        if insight.get("approval", "PROJECT_APPROVED") == "PROJECT_APPROVED":
            results.append(
                InsightSummary(
                    id=insight.get("id", ""),
                    taskId=insight.get("taskId", ""),
                    confidence=insight.get("confidence", 0.0),
                    supportCount=insight.get("supportCount", 0),
                    workflowStepCount=len(insight.get("successfulWorkflow", [])),
                    correctionCount=len(insight.get("corrections", [])),
                    provenance=insight.get("provenance"),
                )
            )
    return results


@router.get("/emg/insights/{insight_id}", response_model=InsightDetail)
def get_emg_insight(insight_id: str) -> InsightDetail:
    """Get full insight detail with provenance."""
    store, used_durable = _read_store_or_memory()

    if used_durable:
        rec = store.get_insight(insight_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"insight not found: {insight_id}")
        insight = rec.insight
        workflow = getattr(insight, "successful_workflow", []) or []
        corrections = getattr(insight, "corrections", []) or []
        prov = getattr(insight, "provenance", None)
        if prov is not None and hasattr(prov, "to_dict"):
            prov = prov.to_dict()
        return InsightDetail(
            id=rec.id,
            taskId=rec.trajectory_id or "",
            successfulWorkflow=list(workflow),
            corrections=list(corrections),
            confidence=float(getattr(insight, "confidence", 0.0) or 0.0),
            supportCount=int(getattr(insight, "support_count", 0) or 0),
            provenance=prov if isinstance(prov, dict) else None,
        )

    insight = store.get(insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail=f"insight not found: {insight_id}")
    return InsightDetail(
        id=insight.get("id", ""),
        taskId=insight.get("taskId", ""),
        successfulWorkflow=insight.get("successfulWorkflow", []),
        corrections=insight.get("corrections", []),
        confidence=insight.get("confidence", 0.0),
        supportCount=insight.get("supportCount", 0),
        provenance=insight.get("provenance"),
    )


@router.get("/emg/stats", response_model=EMGStats)
def get_emg_stats() -> EMGStats:
    """Get EMG corpus statistics.

    WP-08 A-003: surfaces the persisted store's embedding config (backend,
    model, dim, path, compatibility flag) so the UI can show whether the
    store is the TF-IDF CI default or the Gemma product default.
    """
    store, used_durable = _read_store_or_memory()

    if used_durable:
        manifest = store.manifest()
        stats = store.stats()
        return EMGStats(
            totalTrajectories=stats.get("tasks", 0),
            approvedInsights=stats.get("insights", 0),
            crossTaskEdges=stats.get("edges", 0),
            retrievalHitRate=0.0,  # populated by agent-eval harness, not the store
            adapterFamilies=["http", "sftp", "soap", "odata", "idoc", "mail"],
            embeddingBackend=manifest.embedding_backend,
            embeddingModel=manifest.embedding_model,
            embeddingDim=manifest.embedding_dim,
            storePath=str(store.root_path),
            compatible=store.compatible,
        )

    return EMGStats(
        totalTrajectories=_STATS.get("totalTrajectories", len(_INSIGHT_STORE)),
        approvedInsights=len([i for i in _INSIGHT_STORE.values() if i.get("approval") == "PROJECT_APPROVED"]),
        crossTaskEdges=_STATS.get("crossTaskEdges", 0),
        retrievalHitRate=_STATS.get("retrievalHitRate", 0.0),
        adapterFamilies=_STATS.get("adapterFamilies", ["http", "sftp", "soap", "odata", "idoc", "mail"]),
        embeddingBackend="(in-memory-test)",
        embeddingModel="",
        embeddingDim=0,
        storePath="(in-memory-test)",
        compatible=False,
    )
