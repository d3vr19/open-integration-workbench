"""P5b world dynamics + P5c oracle reward tests.

P5b: declarative fault scenarios compile to engine mocks and produce
realistic failures through the real execution engine.
P5c: calibration reports map onto the 9-dim reward vector; failures
capture as learning sessions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.runtime.engine import execute_flow  # noqa: E402
from oiw.runtime.world import (  # noqa: E402
    Fault,
    ReceiverWorld,
    WorldScenario,
    build_world_mocks,
    scenario_from_dict,
)
from oiw.tenant.calibrate import CalibrationReport  # noqa: E402
from oiw.tenant.oracle_feedback import (  # noqa: E402
    failure_diagnostic,
    reward_from_calibration,
    reward_section,
)


def _flow_with_receiver():
    from oiw.project import Entrypoint, FlowEdge, FlowNode, IntegrationFlow

    return IntegrationFlow(
        id="t",
        name="t",
        version=1,
        entrypoints=[Entrypoint(id="s", type="sender.http", config={"path": "/t", "methods": ["GET"]})],
        edges=[FlowEdge(from_="s", to="recv")],
        nodes=[
            FlowNode(
                id="recv", type="receiver.http", config={"url": "https://api.example.com/x", "method": "GET"}
            )
        ],
    )


def _run(mocks):
    return execute_flow(_flow_with_receiver(), b"", {}, mocks=mocks)


# ---------- P5b ----------


def test_happy_world_returns_configured_body():
    world = WorldScenario("w", [ReceiverWorld("recv", status=200, body='{"ok":true}')])
    ctx = _run(build_world_mocks(world))
    assert ctx.exchange_status == "COMPLETED"
    assert b'"ok":true' in ctx.body


def test_timeout_fault_raises():
    world = WorldScenario("w", [ReceiverWorld("recv", faults=[Fault(kind="timeout")])])
    ctx = _run(build_world_mocks(world))
    assert ctx.exchange_status == "FAILED"
    assert isinstance(ctx.exception, TimeoutError)


def test_connection_reset_fault_raises():
    world = WorldScenario("w", [ReceiverWorld("recv", faults=[Fault(kind="connection_reset")])])
    ctx = _run(build_world_mocks(world))
    assert ctx.exception is not None and "reset" in str(ctx.exception).lower()


def test_http_status_fault_sets_status_header():
    world = WorldScenario("w", [ReceiverWorld("recv", faults=[Fault(kind="http_status", status=503)])])
    ctx = _run(build_world_mocks(world))
    assert ctx.headers["HTTP_Status"] == "503"


def test_malformed_fault_truncates_body():
    world = WorldScenario(
        "w",
        [
            ReceiverWorld(
                "recv", body='{"latitude": 52.52, "longitude": 13.41}', faults=[Fault(kind="malformed")]
            )
        ],
    )
    ctx = _run(build_world_mocks(world))
    body = ctx.body.decode()
    import json

    with pytest.raises(json.JSONDecodeError):
        json.loads(body)  # downstream parsers must fail naturally


def test_drift_fault_removes_fields():
    world = WorldScenario(
        "w",
        [
            ReceiverWorld(
                "recv",
                body='{"a": 1, "current": {"temperature_2m": 16.4}}',
                faults=[Fault(kind="drift", remove=["current"])],
            )
        ],
    )
    ctx = _run(build_world_mocks(world))
    assert "current" not in ctx.body.decode()


def test_scenario_from_dict_roundtrip():
    sc = scenario_from_dict(
        {
            "name": "flaky",
            "receivers": {
                "fetch-weather": {
                    "status": 200,
                    "body": '{"t": 1}',
                    "faults": [{"kind": "http_status", "status": 503}],
                }
            },
        }
    )
    mocks = build_world_mocks(sc)
    assert mocks["fetch-weather"]["respond"]["status"] == 503


# ---------- P5c ----------


def test_reward_full_success():
    rep = CalibrationReport(package_id="P", artifact_id="A")
    rep.uploaded_ok = True
    rep.deploy_accepted = True
    rep.final_status = "STARTED"
    rep.message_sent = True
    rep.http_response_status = 200
    rep.mpl_rows = [{"Status": "COMPLETED"}, {"Status": "COMPLETED"}]
    r = reward_from_calibration(rep)
    assert r.completion == 1.0
    assert r.deployment_success == 1.0
    assert r.runtime_stability == 1.0
    assert r.all_hard_gates_passed
    section = reward_section(r)
    assert section["reward"]["overall"] > 0.9


def test_reward_runtime_start_failure_scores_zero_completion():
    rep = CalibrationReport(package_id="P", artifact_id="A")
    rep.uploaded_ok = True
    rep.deploy_accepted = True
    rep.final_status = "ERROR"
    rep.error_detail = "runtime start failed"
    r = reward_from_calibration(rep)
    assert r.completion == 0.0
    assert r.unit_tests == 0.0
    assert failure_diagnostic(rep) == "ORACLE-RUNTIME-START-FAILED"


def test_reward_partial_mpl_failures_reduce_stability():
    rep = CalibrationReport(package_id="P", artifact_id="A")
    rep.uploaded_ok = True
    rep.deploy_accepted = True
    rep.final_status = "STARTED"
    rep.message_sent = True
    rep.mpl_rows = [{"Status": "COMPLETED"}, {"Status": "FAILED"}]
    r = reward_from_calibration(rep)
    assert r.completion == 0.0
    assert r.runtime_stability == 0.5
    assert failure_diagnostic(rep) == "ORACLE-MESSAGE-FAILED"


def test_deploy_only_without_start_is_half_credit():
    rep = CalibrationReport(package_id="P", artifact_id="A")
    rep.uploaded_ok = True
    rep.deploy_accepted = True
    rep.final_status = "TIMEOUT"
    r = reward_from_calibration(rep)
    assert r.deployment_success == 0.5
    assert r.completion == 0.0
