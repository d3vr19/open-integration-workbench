"""Tests for EMG API endpoints (WP-06 Track E Task E-003)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_emg_insights_empty() -> None:
    """GET /emg/insights returns empty list when store is empty."""
    from oiw_server.main import app
    from oiw_server.routes.emg import populate_emg_api

    populate_emg_api(insights=[])
    client = TestClient(app)
    r = client.get("/api/v1/projects/test/emg/insights")
    assert r.status_code == 200
    assert r.json() == []


def test_list_emg_insights_with_data() -> None:
    """GET /emg/insights returns insights when populated."""
    from oiw_server.main import app
    from oiw_server.routes.emg import populate_emg_api

    populate_emg_api(
        insights=[
            {
                "id": "insight-1",
                "taskId": "task-validate",
                "confidence": 0.9,
                "supportCount": 3,
                "successfulWorkflow": [{"action": ["flow.patch", "addNode", "validator.json-schema"]}],
                "corrections": [],
                "provenance": {"matchStage": "exact"},
                "approval": "PROJECT_APPROVED",
            }
        ]
    )
    client = TestClient(app)
    r = client.get("/api/v1/projects/test/emg/insights")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == "insight-1"
    assert data[0]["confidence"] == 0.9
    assert data[0]["supportCount"] == 3


def test_get_emg_insight_detail() -> None:
    """GET /emg/insights/{id} returns full insight detail."""
    from oiw_server.main import app
    from oiw_server.routes.emg import populate_emg_api

    populate_emg_api(
        insights=[
            {
                "id": "insight-detail",
                "taskId": "task-detail",
                "confidence": 0.85,
                "supportCount": 2,
                "successfulWorkflow": [{"action": ["flow.patch", "addNode", "log.message"]}],
                "corrections": [{"trigger": {"diagnostic": "FAILED"}, "avoid": [], "prefer": []}],
                "provenance": {"matchStage": "rule-based"},
            }
        ]
    )
    client = TestClient(app)
    r = client.get("/api/v1/emg/insights/insight-detail")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "insight-detail"
    assert len(data["successfulWorkflow"]) == 1
    assert len(data["corrections"]) == 1


def test_get_emg_insight_not_found() -> None:
    """GET /emg/insights/{id} returns 404 for unknown insight."""
    from oiw_server.main import app
    from oiw_server.routes.emg import populate_emg_api

    populate_emg_api(insights=[])
    client = TestClient(app)
    r = client.get("/api/v1/emg/insights/nonexistent")
    assert r.status_code == 404


def test_get_emg_stats() -> None:
    """GET /emg/stats returns corpus statistics."""
    from oiw_server.main import app
    from oiw_server.routes.emg import populate_emg_api

    populate_emg_api(
        insights=[
            {
                "id": "s1",
                "taskId": "t1",
                "confidence": 0.9,
                "supportCount": 1,
                "successfulWorkflow": [],
                "corrections": [],
                "approval": "PROJECT_APPROVED",
            }
        ],
        stats={"totalTrajectories": 50, "crossTaskEdges": 5, "retrievalHitRate": 0.75},
    )
    client = TestClient(app)
    r = client.get("/api/v1/emg/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["totalTrajectories"] == 50
    assert data["approvedInsights"] == 1
    assert data["crossTaskEdges"] == 5
    assert data["retrievalHitRate"] == 0.75
