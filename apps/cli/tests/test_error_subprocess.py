"""Test that the error subprocess is executed when a step fails.

Spec ref: §7.2 (errorHandling.defaultExceptionSubprocess), §9.4 (subprocess.exception).
Feedback item #10: verify error subprocess execution is not decorative.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oiw.project import Project
from oiw.runtime.engine import execute_flow

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "order-to-s4"


@pytest.fixture(scope="module")
def project() -> Project:
    return Project.load(EXAMPLE)


def test_error_subprocess_executes_on_validation_failure(project: Project) -> None:
    """When validation fails, the error subprocess steps should execute."""
    flow = project.get_flow("order-to-s4")

    # Invalid payload — missing required fields
    body = b'{"orderId":"ORD-002"}'  # missing customerId, region, items
    ctx = execute_flow(
        flow=flow,
        input_body=body,
        input_headers={"Content-Type": "application/json"},
        resources=project.resources,
        mocks={},
    )

    # The flow should fail
    assert ctx.exchange_status == "FAILED"

    # The error subprocess steps should have executed
    # The errorHandling block has: log-error (log.message) + set-500 (modifier.content)
    trace_node_ids = {t.node_id for t in ctx.trace}
    assert "log-error" in trace_node_ids, (
        f"Error subprocess 'log-error' step was not executed. " f"Trace node IDs: {trace_node_ids}"
    )
    assert "set-500" in trace_node_ids, (
        f"Error subprocess 'set-500' step was not executed. " f"Trace node IDs: {trace_node_ids}"
    )

    # The set-500 step should have set HTTP_Status to 500
    assert (
        ctx.headers.get("HTTP_Status") == "500"
    ), f"Error subprocess did not set HTTP_Status=500. Headers: {ctx.headers}"

    # The body should be the error response
    assert (
        b"Internal processing failure" in ctx.body
    ), f"Error subprocess did not set the error body. Body: {ctx.body}"


def test_error_subprocess_not_executed_on_success(project: Project) -> None:
    """When the flow succeeds, the error subprocess steps should NOT execute."""
    flow = project.get_flow("order-to-s4")

    # Valid payload
    body = (
        b'{"orderId":"ORD-001","customerId":"CUST-42","region":"EU","items":[{"sku":"SKU-A","quantity":2}]}'
    )
    ctx = execute_flow(
        flow=flow,
        input_body=body,
        input_headers={"Content-Type": "application/json"},
        resources=project.resources,
        mocks={
            "receiver-s4-eu": {
                "target": "receiver-s4-eu",
                "respond": {"status": 201, "body": '{"id":"4711"}'},
            }
        },
    )

    assert ctx.exchange_status == "COMPLETED"

    # Error subprocess steps should NOT be in the trace
    trace_node_ids = {t.node_id for t in ctx.trace}
    assert "log-error" not in trace_node_ids, "Error subprocess 'log-error' should not execute on success"
    assert "set-500" not in trace_node_ids, "Error subprocess 'set-500' should not execute on success"
