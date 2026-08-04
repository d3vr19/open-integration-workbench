"""EMG insight routes — expose EMG insights + stats to the UI.

WP-06 Track E Task E-003.
Spec ref: §15.11 (Retrieval), §15.14 (Seed Corpus).
"""

from __future__ import annotations

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


# In-memory store for the API (populated by the seed corpus at startup).
# In production this would be a database.
_INSIGHT_STORE: dict[str, dict] = {}
_STATS: dict[str, any] = {}


def populate_emg_api(insights: list[dict], stats: dict | None = None) -> None:
    """Populate the EMG API store (called at startup or by tests)."""
    global _STATS
    _INSIGHT_STORE.clear()
    for insight in insights:
        _INSIGHT_STORE[insight.get("id", "")] = insight
    if stats:
        _STATS = stats


@router.get("/projects/{project_id}/emg/insights", response_model=list[InsightSummary])
def list_emg_insights(project_id: str) -> list[InsightSummary]:
    """List all approved EMG insights for a project."""
    results = []
    for insight in _INSIGHT_STORE.values():
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
    insight = _INSIGHT_STORE.get(insight_id)
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
    """Get EMG corpus statistics."""
    return EMGStats(
        totalTrajectories=_STATS.get("totalTrajectories", len(_INSIGHT_STORE)),
        approvedInsights=len([i for i in _INSIGHT_STORE.values() if i.get("approval") == "PROJECT_APPROVED"]),
        crossTaskEdges=_STATS.get("crossTaskEdges", 0),
        retrievalHitRate=_STATS.get("retrievalHitRate", 0.0),
        adapterFamilies=_STATS.get("adapterFamilies", ["http", "sftp", "soap", "odata", "idoc", "mail"]),
    )
