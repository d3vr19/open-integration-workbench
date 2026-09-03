"""Body-position helpers for law checks (shared with the experiment engine).

A node's "body position" is its index in the deterministic execution order
of the flow body (entrypoints excluded) — the same order semantics the
experiment engine's move-rungs use (`engine.execution_order` + body filter).
Keeping this in ONE place guarantees a law derived at position N warns at
position N.
"""

from __future__ import annotations

from typing import Any

from ..project import IntegrationFlow


def body_order(flow: IntegrationFlow) -> list[str]:
    """Deterministic execution order of the flow body (entrypoints excluded)."""
    from ..experiment.engine import execution_order

    entry_ids = {e.id for e in flow.entrypoints}
    return [nid for nid in execution_order(flow) if nid not in entry_ids]


def body_position(flow: IntegrationFlow, node_id: str) -> int | None:
    order = body_order(flow)
    return order.index(node_id) if node_id in order else None


def position_of(flow: IntegrationFlow, node_type: str) -> int | None:
    """Body position of the FIRST node matching `node_type`, else None."""
    for nid in body_order(flow):
        node = _find(flow, nid)
        if node is not None and node.type == node_type:
            return body_position(flow, nid)
    return None


def _find(flow: IntegrationFlow, node_id: str) -> Any | None:
    for n in flow.nodes:
        if n.id == node_id:
            return n
    return None


__all__ = ["body_order", "body_position", "position_of"]
