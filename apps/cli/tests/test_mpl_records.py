"""MPL-shaped local trace records (P5a-M2).

Local runs must be structurally comparable to tenant MessageProcessingLogs:
same field names/status vocabulary, /Date(ms)/ time wrapper, honest
provenance (Origin=local-sim).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.runtime.context import MessageContext  # noqa: E402
from oiw.runtime.mpl import mpl_records_from_context  # noqa: E402

_DATE_RE = re.compile(r"^/Date\(\d+\)/$")


def _ctx(status: str = "COMPLETED", exc: BaseException | None = None) -> MessageContext:
    ctx = MessageContext(body=b"{}", content_type="application/json")
    ctx.exchange_status = status
    ctx.exception = exc
    return ctx


def test_completed_record_has_tenant_vocabulary():
    ctx = _ctx()
    ctx.add_trace("log-1", "exit", "logged")
    rows = mpl_records_from_context(ctx, "my_flow", message_guid="OIW-fixed")
    assert len(rows) == 1
    row = rows[0]
    assert row["MessageGuid"] == "OIW-fixed"
    assert row["Status"] == "COMPLETED"
    assert row["CustomStatus"] == "COMPLETED"
    assert row["IntegrationFlowName"] == "my_flow"
    assert _DATE_RE.match(row["LogStart"])
    assert _DATE_RE.match(row["LogEnd"])
    # provenance: never mistakable for a tenant row
    assert row["Origin"] == "local-sim"


def test_failed_status_propagates():
    rows = mpl_records_from_context(_ctx("FAILED", RuntimeError("boom")), "f")
    assert rows[0]["Status"] == "FAILED"
    assert rows[0]["CustomStatus"] == "FAILED"


def test_exception_alone_means_failed():
    rows = mpl_records_from_context(_ctx("RUNNING", ValueError("x")), "f")
    assert rows[0]["Status"] == "FAILED"


def test_step_rows_in_execution_order_with_error_marking():
    ctx = _ctx()
    ctx.add_trace("a", "enter", "in")
    ctx.add_trace("a", "exit", "ok")
    ctx.add_trace("b", "error", "kaboom")
    rows = mpl_records_from_context(ctx, "f")
    steps = rows[0]["steps"]
    assert [s["StepId"] for s in steps] == ["a", "b"]
    by_id = {s["StepId"]: s["Status"] for s in steps}
    assert by_id["a"] == "COMPLETED"
    assert by_id["b"] == "FAILED"


def test_engine_and_synthetic_nodes_excluded_from_steps():
    ctx = _ctx()
    ctx.add_trace("__flow__", "complete", "done")
    ctx.add_trace("__engine__", "error", "refused")
    ctx.add_trace("real-step", "exit", "ok")
    rows = mpl_records_from_context(ctx, "f")
    assert [s["StepId"] for s in rows[0]["steps"]] == ["real-step"]
