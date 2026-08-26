"""MPL-shaped trace records (P5a-M2).

Local executions must be structurally comparable to tenant ground truth
(p5-p6-plan.md §0): this module renders a finished MessageContext as
MessageProcessingLog-shaped rows using the SAME field names and status
vocabulary the tenant API serves (verified live, §6):

    MessageGuid, Status (COMPLETED|FAILED), CustomStatus,
    IntegrationFlowName, LogStart/LogEnd wrapped as /Date(<epoch-ms>)/

Honesty rules:
  - Records carry Origin=local-sim; they are a SUPERSET of tenant fields
    (extra keys: Origin, steps) so structural comparison never mistakes
    them for tenant rows.
  - Only what actually happened is recorded: step rows are derived from
    the engine trace (executed nodes only).
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from .context import MessageContext

COMPLETED = "COMPLETED"
FAILED = "FAILED"


def _log_time(epoch_s: float | None = None) -> str:
    ms = int((epoch_s if epoch_s is not None else time.time()) * 1000)
    return f"/Date({ms})/"


def mpl_records_from_context(
    ctx: MessageContext,
    flow_name: str,
    *,
    message_guid: str | None = None,
) -> list[dict[str, Any]]:
    """Build MPL-shaped records from an executed local exchange.

    Returns a single-element list (one row per exchange, mirroring the
    tenant's per-message log shape). `message_guid` allows deterministic
    records for tests; production callers omit it.
    """
    failed = ctx.exchange_status == "FAILED" or ctx.exception is not None
    status = FAILED if failed else COMPLETED

    timestamps = [t.timestamp for t in ctx.trace if t.timestamp]
    log_start = _log_time(min(timestamps)) if timestamps else _log_time()
    log_end = _log_time()

    row: dict[str, Any] = {
        "MessageGuid": message_guid or f"OIW-{uuid.uuid4()}",
        "Status": status,
        "CustomStatus": status,
        "IntegrationFlowName": flow_name,
        "LogStart": log_start,
        "LogEnd": log_end,
        "Origin": "local-sim",
        "steps": _step_rows_from_trace(ctx),
    }
    return [row]


def _step_rows_from_trace(ctx: MessageContext) -> list[dict[str, Any]]:
    """One row per executed node, in first-appearance order.

    A node is FAILED iff the engine traced an error direction for it;
    everything else counts COMPLETED (matching the vocabulary, not
    pretending at tenant-internal step semantics we cannot observe).
    """
    order: list[str] = []
    errored: set[str] = set()
    for entry in ctx.trace:
        if entry.node_id == "__flow__" or entry.node_id == "__engine__":
            continue
        if entry.node_id not in order:
            order.append(entry.node_id)
        if entry.direction == "error":
            errored.add(entry.node_id)
    return [
        {"StepId": node_id, "Status": FAILED if node_id in errored else COMPLETED}
        for node_id in order
    ]


__all__ = ["COMPLETED", "FAILED", "mpl_records_from_context"]
