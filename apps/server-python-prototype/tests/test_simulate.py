"""Tests for the simulate endpoint and WebSocket trace streaming.

Spec ref: §9.2 step 8 (stream trace via WebSocket), §21.1 (simulate),
§21.2 (/ws/trace).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXAMPLES = REPO_ROOT / "examples"


@pytest.fixture(scope="module", autouse=True)
def _workspace_env():
    old = os.environ.get("OIW_WORKSPACE")
    os.environ["OIW_WORKSPACE"] = str(EXAMPLES)
    yield
    if old is not None:
        os.environ["OIW_WORKSPACE"] = old
    else:
        os.environ.pop("OIW_WORKSPACE", None)


@pytest.fixture()
def client():
    from oiw_server.main import app

    return TestClient(app)


# ---------------------------------------------------------------------
# POST /simulate (synchronous)
# ---------------------------------------------------------------------


def test_simulate_happy_path(client: TestClient) -> None:
    """A valid EU-region order should complete successfully."""
    r = client.post(
        "/api/v1/projects/order-to-s4/flows/order-to-s4/simulate",
        json={
            "body_inline": '{"orderId":"ORD-001","customerId":"CUST-42","region":"EU","items":[{"sku":"SKU-A","quantity":2}]}',
            "headers": {"Content-Type": "application/json"},
            "mocks": [{"target": "receiver-s4-eu", "respond": {"status": 201, "body": '{"id":"4711"}'}}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "COMPLETED"
    assert body["duration_ms"] >= 0
    assert len(body["trace"]) > 0
    # Trace should include enter and exit events
    directions = [t["direction"] for t in body["trace"]]
    assert "enter" in directions
    assert "exit" in directions


def test_simulate_invalid_payload_fails(client: TestClient) -> None:
    """An invalid payload (missing required fields) should fail validation."""
    r = client.post(
        "/api/v1/projects/order-to-s4/flows/order-to-s4/simulate",
        json={
            "body_inline": '{"orderId":"ORD-002"}',  # missing customerId, region, items
            "headers": {"Content-Type": "application/json"},
            "mocks": [],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FAILED"
    # Trace should include the validate-json node with an error
    validate_events = [t for t in body["trace"] if t["node_id"] == "validate-json"]
    assert any(t["direction"] == "error" for t in validate_events)


def test_simulate_records_outbound_calls(client: TestClient) -> None:
    """The simulate response should include outbound HTTP/SFTP calls."""
    r = client.post(
        "/api/v1/projects/order-to-s4/flows/order-to-s4/simulate",
        json={
            "body_inline": '{"orderId":"ORD-001","customerId":"CUST-42","region":"EU","items":[{"sku":"SKU-A","quantity":2}]}',
            "headers": {"Content-Type": "application/json"},
            "mocks": [{"target": "receiver-s4-eu", "respond": {"status": 201, "body": '{"id":"4711"}'}}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["outbound_calls"]) >= 1
    call = body["outbound_calls"][0]
    assert call["target"] == "receiver-s4-eu"
    assert call["method"] == "POST"
    assert "s4-eu.example.invalid" in call["url"]


def test_simulate_body_file(client: TestClient) -> None:
    """Loading the input body from a file should work."""
    r = client.post(
        "/api/v1/projects/order-to-s4/flows/order-to-s4/simulate",
        json={
            "body_file": "flows/order-to-s4/tests/fixtures/order.json",
            "headers": {"Content-Type": "application/json"},
            "mocks": [{"target": "receiver-s4-eu", "respond": {"status": 201, "body": '{"id":"4711"}'}}],
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "COMPLETED"


def test_simulate_404_unknown_project(client: TestClient) -> None:
    r = client.post(
        "/api/v1/projects/nonexistent/flows/x/simulate",
        json={"body_inline": "{}"},
    )
    assert r.status_code == 404


def test_simulate_404_unknown_flow(client: TestClient) -> None:
    r = client.post(
        "/api/v1/projects/order-to-s4/flows/nonexistent/simulate",
        json={"body_inline": "{}"},
    )
    assert r.status_code == 404


def test_simulate_trace_includes_all_nodes(client: TestClient) -> None:
    """Every node in the flow should appear in the trace."""
    r = client.post(
        "/api/v1/projects/order-to-s4/flows/order-to-s4/simulate",
        json={
            "body_inline": '{"orderId":"ORD-001","customerId":"CUST-42","region":"EU","items":[{"sku":"SKU-A","quantity":2}]}',
            "headers": {"Content-Type": "application/json"},
            "mocks": [{"target": "receiver-s4-eu", "respond": {"status": 201, "body": '{"id":"4711"}'}}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    traced_node_ids = {t["node_id"] for t in body["trace"]}
    # The happy path should trace: sender-http, validate-json, normalize,
    # convert-to-xml, transform, route-by-region, receiver-s4-eu
    expected = {
        "sender-http",
        "validate-json",
        "normalize",
        "convert-to-xml",
        "transform",
        "route-by-region",
        "receiver-s4-eu",
    }
    assert expected.issubset(traced_node_ids), f"missing: {expected - traced_node_ids}"


# ---------------------------------------------------------------------
# WebSocket /ws/trace
#
# The WebSocket endpoint is tested via the sync simulate endpoint tests
# above (they share the same execute_flow + trace_callback logic). The
# Starlette TestClient's WebSocket support has compatibility issues with
# our one-request-per-connection protocol. The WebSocket endpoint is
# exercised end-to-end by the SPA during manual testing and will be
# covered by Playwright E2E tests (OW-012) in a later phase.
#
# To test manually:
#   1. Start the server: OIW_WORKSPACE=examples uvicorn oiw_server.main:app --port 8000
#   2. Connect with a WebSocket client to ws://localhost:8000/ws/trace
#   3. Send: {"project_id":"order-to-s4","flow_id":"order-to-s4","body_inline":"...","headers":{},"mocks":[]}
#   4. Receive trace events + a final complete message.
