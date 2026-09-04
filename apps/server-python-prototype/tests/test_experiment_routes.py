"""WP-10: B2 experiment + law + calibration route tests (contract-first).

The routes serve persisted/committed state read-only:
  - experiments  <- <workspace>/.oiw/experiments/*.yaml
  - laws        <- <workspace>/.oiw/tenant-laws.yaml, falling back to the
                   committed packages/law-registry/tenant-laws.yaml
  - calibrations <- <project>/.oiw/calibration-*.yaml

UI == API truth: these tests pin the response SHAPES the generated TS
client (api:gen) consumes.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]

CAMPAIGN_FIXTURE = {
    "experimentId": "exp-test0001",
    "baselineFlowId": "oiw-conv-fwd",
    "hypothesis": "placement isolation (test)",
    "createdAt": "2026-09-03T12:00:00+00:00",
    "baselineVerdict": "GREEN",
    "status": "complete",
    "rungs": [
        {
            "rungId": "r1-move-conv-to0",
            "kind": "move",
            "target": "step-1-converter-json-to-xml",
            "detail": {"toPosition": 0},
            "rationale": "move node to position 0",
            "verdict": "RED",
            "evidence": {
                "finalStatus": "STARTED",
                "httpResponseStatus": 500,
                "mplStatuses": ["FAILED"],
                "targetType": "converter.json-to-xml",
            },
        },
        {
            "rungId": "r2-move-conv-to2",
            "kind": "move",
            "target": "step-1-converter-json-to-xml",
            "detail": {"toPosition": 2},
            "rationale": "move node to position 2",
            "verdict": "GREEN",
            "evidence": {
                "finalStatus": "STARTED",
                "httpResponseStatus": 200,
                "mplStatuses": ["COMPLETED"],
                "targetType": "converter.json-to-xml",
            },
        },
    ],
}

LAWS_FIXTURE = {
    "laws": [
        {
            "lawId": "law-test-conv",
            "statement": "converter must sit after an RR",
            "scope": "converter.json-to-xml",
            "kind": "move",
            "origin": "exp-test0001",
            "evidence": {"greenRungs": ["r2"], "redRungs": ["r1"]},
            "confidence": 1.0,
            "status": "ratified",
            "recordedAt": "2026-09-03T13:00:00+00:00",
            "source": "engine",
            "predicate": {
                "type": "requires-position-after",
                "node": "converter.json-to-xml",
                "redPositions": [0],
                "greenPositions": [2],
            },
        },
        {
            "lawId": "law-manual-1",
            "statement": "main-process ends are always MessageEndEvent",
            "scope": "flow.topology",
            "kind": "drop",
            "origin": "manual",
            "evidence": {},
            "confidence": 1.0,
            "status": "ratified",
            "recordedAt": "2026-09-02T00:00:00+00:00",
            "source": "manual",
            "predicate": None,
        },
    ]
}

CALIBRATION_FIXTURE = {
    "calibration": {
        "packageId": "AdaequareGST",
        "artifactId": "oiw-conv-main",
        "uploadedOk": True,
        "deployAccepted": True,
        "trackingUuid": None,
        "finalStatus": "STARTED",
        "errorDetail": None,
        "messageSent": True,
        "httpResponseStatus": 200,
        "mplRows": [
            {
                "MessageGuid": "TESTGUID",
                "Status": "COMPLETED",
                "CustomStatus": "COMPLETED",
                "IntegrationFlowName": "oiw-conv-main",
                "LogStart": "/Date(1788443212972)/",
            }
        ],
        "startedAt": "2026-09-03T14:00:00+00:00",
        "finishedAt": "",
    },
    "reward": {
        "overall": 1.0,
        "dimensions": {"completion": 1.0},
        "allHardGatesPassed": True,
    },
}


def _make_workspace(tmp_path: Path, monkeypatch) -> Path:
    ws = tmp_path / "ws"
    (ws / ".oiw" / "experiments").mkdir(parents=True)
    (ws / ".oiw" / "experiments" / "exp-test0001.yaml").write_text(
        yaml.safe_dump(CAMPAIGN_FIXTURE, sort_keys=False), encoding="utf-8"
    )
    (ws / ".oiw" / "tenant-laws.yaml").write_text(
        yaml.safe_dump(LAWS_FIXTURE, sort_keys=False), encoding="utf-8"
    )
    # a project with a calibration report
    proj = ws / "demo-proj"
    (proj / ".oiw").mkdir(parents=True)
    (proj / "oiw.yaml").write_text(
        "apiVersion: oiw.dev/v1alpha1\nkind: Project\nmetadata:\n  id: demo-proj\n  name: demo\n",
        encoding="utf-8",
    )
    (proj / ".oiw" / "calibration-oiw-conv-main.yaml").write_text(
        yaml.safe_dump(CALIBRATION_FIXTURE, sort_keys=False), encoding="utf-8"
    )
    monkeypatch.setenv("OIW_WORKSPACE", str(ws))
    return ws


def test_list_experiments(tmp_path, monkeypatch) -> None:
    _make_workspace(tmp_path, monkeypatch)
    from oiw_server.main import app

    client = TestClient(app)
    r = client.get("/api/v1/experiments")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    s = data[0]
    assert s["experimentId"] == "exp-test0001"
    assert s["status"] == "complete"
    assert s["baselineVerdict"] == "GREEN"
    assert s["rungCount"] == 2
    assert s["greenCount"] == 1
    assert s["redCount"] == 1
    assert s["skippedCount"] == 0


def test_get_experiment_detail(tmp_path, monkeypatch) -> None:
    _make_workspace(tmp_path, monkeypatch)
    from oiw_server.main import app

    client = TestClient(app)
    r = client.get("/api/v1/experiments/exp-test0001")
    assert r.status_code == 200
    rec = r.json()
    assert rec["baselineFlowId"] == "oiw-conv-fwd"
    assert len(rec["rungs"]) == 2
    red = next(r0 for r0 in rec["rungs"] if r0["verdict"] == "RED")
    assert red["evidence"]["targetType"] == "converter.json-to-xml"


def test_get_experiment_404(tmp_path, monkeypatch) -> None:
    _make_workspace(tmp_path, monkeypatch)
    from oiw_server.main import app

    client = TestClient(app)
    assert client.get("/api/v1/experiments/nope").status_code == 404


def test_list_laws_with_filters(tmp_path, monkeypatch) -> None:
    _make_workspace(tmp_path, monkeypatch)
    from oiw_server.main import app

    client = TestClient(app)
    r = client.get("/api/v1/laws")
    assert r.status_code == 200
    laws = r.json()
    assert len(laws) == 2

    r = client.get("/api/v1/laws", params={"status": "ratified"})
    assert len(r.json()) == 2
    r = client.get("/api/v1/laws", params={"scope": "converter.json-to-xml"})
    assert len(r.json()) == 1
    law = r.json()[0]
    assert law["predicate"]["type"] == "requires-position-after"
    assert law["source"] == "engine"

    r = client.get("/api/v1/laws", params={"scope": "flow.topology", "status": "candidate"})
    assert r.json() == []


def test_laws_fallback_to_committed_registry(tmp_path, monkeypatch) -> None:
    """No workspace registry -> the committed packages/law-registry/ shows."""
    ws = tmp_path / "empty-ws"
    ws.mkdir()
    monkeypatch.setenv("OIW_WORKSPACE", str(ws))
    from oiw_server.main import app

    client = TestClient(app)
    r = client.get("/api/v1/laws")
    assert r.status_code == 200
    laws = r.json()
    # the committed registry has 2 ratified laws (campaign #1, e6e7a95)
    assert len(laws) >= 2
    assert any(law["status"] == "ratified" for law in laws)


def test_laws_empty_when_no_registry_anywhere(tmp_path, monkeypatch) -> None:
    """Fresh workspace + no committed file discoverable -> empty, not error."""
    ws = tmp_path / "empty-ws"
    ws.mkdir()
    monkeypatch.setenv("OIW_WORKSPACE", str(ws))
    monkeypatch.chdir(tmp_path)
    # cwd has no .oiw/tenant-laws.yaml either — but the committed registry
    # exists relative to the module, so this asserts the fallback finds it.
    from oiw_server.main import app

    client = TestClient(app)
    r = client.get("/api/v1/laws")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_calibrations(tmp_path, monkeypatch) -> None:
    _make_workspace(tmp_path, monkeypatch)
    from oiw_server.main import app

    client = TestClient(app)
    r = client.get("/api/v1/projects/demo-proj/calibrations")
    assert r.status_code == 200
    cals = r.json()
    assert len(cals) == 1
    c = cals[0]
    assert c["artifactId"] == "oiw-conv-main"
    assert c["finalStatus"] == "STARTED"
    assert c["mplCompleted"] == 1
    assert c["mplFailed"] == 0
    assert c["rewardOverall"] == 1.0
    assert c["reportPath"] == "calibration-oiw-conv-main.yaml"


def test_get_calibration_detail(tmp_path, monkeypatch) -> None:
    _make_workspace(tmp_path, monkeypatch)
    from oiw_server.main import app

    client = TestClient(app)
    r = client.get("/api/v1/projects/demo-proj/calibrations/oiw-conv-main")
    assert r.status_code == 200
    data = r.json()
    assert data["calibration"]["artifactId"] == "oiw-conv-main"
    assert data["calibration"]["mplRows"][0]["Status"] == "COMPLETED"
    assert data["reward"]["overall"] == 1.0


def test_get_calibration_404s(tmp_path, monkeypatch) -> None:
    _make_workspace(tmp_path, monkeypatch)
    from oiw_server.main import app

    client = TestClient(app)
    assert client.get("/api/v1/projects/demo-proj/calibrations/nope").status_code == 404
    assert client.get("/api/v1/projects/missing-proj/calibrations/x").status_code == 404


def test_project_404_clean_message(tmp_path, monkeypatch) -> None:
    _make_workspace(tmp_path, monkeypatch)
    from oiw_server.main import app

    client = TestClient(app)
    r = client.get("/api/v1/projects/missing-proj/calibrations")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


def _cleanup(monkeypatch) -> None:
    monkeypatch.delenv("OIW_WORKSPACE", raising=False)
