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


# ---------------------------------------------------------------------------
# WP-08 PR-3 / Track A-003: persisted-store reads
# ---------------------------------------------------------------------------


def test_emg_stats_reads_persisted_store(tmp_path, monkeypatch) -> None:
    """GET /emg/stats serves counts from the persisted JsonlEmgStore (WP-08 A-003).

    Acceptance: `GET /api/v1/emg/stats` and `oiw emg status` agree after a restart.
    """
    from fastapi.testclient import TestClient

    from oiw_server.main import app
    from oiw_server.routes import emg as emg_routes

    # Reset module-level state
    emg_routes._EMG_STORE = None
    monkeypatch.setenv("OIW_WORKSPACE", str(tmp_path))

    # Populate the durable store directly via the JsonlEmgStore API.
    # Use the default dim (53) so the server's auto-loaded store stays compatible.
    import sys

    cli_src = str(__import__("pathlib").Path(__file__).resolve().parents[2] / "apps" / "cli")
    if cli_src not in sys.path:
        sys.path.insert(0, cli_src)
    from oiw.agent.interpreter import NormalizedRequirement
    from oiw.emg.promotion import InsightRecord, MemoryPromotionState
    from oiw.emg.store import JsonlEmgStore

    store = JsonlEmgStore(root=tmp_path / ".oiw" / "emg")
    store.load()
    store.upsert_insight(
        InsightRecord(
            id="dur-1",
            state=MemoryPromotionState.PROJECT_APPROVED,
            project_id="proj-x",
            trajectory_id="traj-1",
        )
    )
    req = NormalizedRequirement(
        intent="add-validation",
        raw="add json schema validation",
        archetype="api-to-erp",
        source_protocol="https",
        target_protocol="https",
        operations=["validate"],
        components=["validator.json-schema"],
    )
    store.upsert_task_from_requirement(req, task_id="task-x", project_id="proj-x")
    store.save()

    client = TestClient(app)
    with client:
        r = client.get("/api/v1/emg/stats")
        assert r.status_code == 200
        data = r.json()
        # Durable path: counts come from the persisted store
        assert data["approvedInsights"] == 1
        assert data["totalTrajectories"] == 1
        assert data["embeddingBackend"] == "tfidf"
        assert data["compatible"] is True


def test_emg_insights_reads_persisted_store(tmp_path, monkeypatch) -> None:
    """GET /projects/{id}/emg/insights serves insights from the persisted store."""
    from fastapi.testclient import TestClient

    from oiw_server.main import app
    from oiw_server.routes import emg as emg_routes

    emg_routes._EMG_STORE = None
    monkeypatch.setenv("OIW_WORKSPACE", str(tmp_path))

    import sys

    cli_src = str(__import__("pathlib").Path(__file__).resolve().parents[2] / "apps" / "cli")
    if cli_src not in sys.path:
        sys.path.insert(0, cli_src)
    from oiw.emg.promotion import InsightRecord, MemoryPromotionState
    from oiw.emg.store import JsonlEmgStore

    store = JsonlEmgStore(root=tmp_path / ".oiw" / "emg")
    store.load()
    store.upsert_insight(
        InsightRecord(
            id="dur-insight-1",
            state=MemoryPromotionState.PROJECT_APPROVED,
            project_id="proj-y",
            trajectory_id="traj-y",
        )
    )
    store.save()

    client = TestClient(app)
    with client:
        r = client.get("/api/v1/projects/proj-y/emg/insights")
        assert r.status_code == 200
        data = r.json()
        # The insight is returned even though the in-memory test store is empty
        ids = [i["id"] for i in data]
        assert "dur-insight-1" in ids
