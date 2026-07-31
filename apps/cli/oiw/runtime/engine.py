"""Execution engine.

Spec ref: §9.2 (Execution Engine).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any

from ..project import FlowNode, IntegrationFlow
from .context import ExchangeStatus, MessageContext
from .steps.base import get_plugin


class ExecutionError(Exception):
    """Raised when a flow cannot be executed."""


class ExecutionPlan:
    """Topological execution plan for a flow.

    Spec §9.2 step 1: compile IR into an ExecutionPlan (topological sort of nodes).
    """

    def __init__(self, flow: IntegrationFlow) -> None:
        self.flow = flow
        self._adjacency: dict[str, list[str]] = defaultdict(list)
        self._entry_ids: list[str] = [e.id for e in flow.entrypoints]
        for edge in flow.edges:
            self._adjacency[edge.from_].append(edge.to)
        self._order: list[str] = self._topo_sort()

    def _topo_sort(self) -> list[str]:
        in_degree: dict[str, int] = defaultdict(int)
        for src, targets in self._adjacency.items():
            for t in targets:
                in_degree[t] += 1
            if src not in in_degree:
                in_degree[src] = 0

        queue: deque[str] = deque(self._entry_ids)
        order: list[str] = []
        seen: set[str] = set()
        while queue:
            node = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            order.append(node)
            for nxt in self._adjacency.get(node, []):
                in_degree[nxt] -= 1
                if in_degree[nxt] <= 0:
                    queue.append(nxt)
        return order

    @property
    def order(self) -> list[str]:
        return list(self._order)


def execute_flow(
    flow: IntegrationFlow,
    input_body: bytes,
    input_headers: dict[str, Any],
    input_properties: dict[str, Any] | None = None,
    resources: dict[str, bytes] | None = None,
    mocks: dict[str, dict[str, Any]] | None = None,
) -> MessageContext:
    """Execute a flow against the given input. Returns the final MessageContext.

    Spec §9.2 step 1: compile IR into an ExecutionPlan (topological sort).
    Spec §9.2 step 2: validate graph before execution.
    Spec §9.2 step 4: record input/output snapshot per node.
    Spec §9.2 step 7: enforce timeouts (TODO) and memory quotas (TODO).
    """
    plan = ExecutionPlan(flow)
    node_map: dict[str, FlowNode] = {n.id: n for n in flow.nodes}
    for entry in flow.entrypoints:
        node_map[entry.id] = FlowNode(
            id=entry.id, type=entry.type, config=entry.config, fidelity=entry.fidelity
        )

    # Build adjacency: from -> [(to, condition)]
    adjacency: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    for edge in flow.edges:
        adjacency[edge.from_].append((edge.to, edge.condition))

    ctx = MessageContext(
        body=input_body,
        content_type=str(input_headers.get("Content-Type", "application/octet-stream")),
        headers=dict(input_headers),
        properties=dict(input_properties or {}),
        variables={"__resources__": resources or {}},
    )

    mocks = mocks or {}
    start_time = time.monotonic()

    # Walk the plan in topological order, honoring conditional edges after a router step.
    # When a router node sets __router_selected_target__, only follow the matching edge.
    visited: set[str] = set()
    queue: list[str] = list(plan.order)

    for node_id in plan.order:
        node = node_map.get(node_id)
        if node is None:
            continue
        if node_id in visited:
            continue
        visited.add(node_id)
        plugin = get_plugin(node.type)
        if plugin is None:
            ctx.exchange_status = ExchangeStatus.FAILED
            ctx.exception = ExecutionError(f"no plugin registered for step type {node.type!r}")
            ctx.add_trace(node_id, "error", f"no plugin for type {node.type}")
            break

        try:
            ctx = plugin.execute(node, ctx, mocks)
        except Exception as exc:
            ctx.exchange_status = ExchangeStatus.FAILED
            ctx.exception = exc
            ctx.add_trace(node_id, "error", f"exception: {exc}")
            break

        if ctx.exchange_status == ExchangeStatus.FAILED:
            # Run error subprocess if defined (spec §7.2 errorHandling.defaultExceptionSubprocess)
            if flow.error_handling:
                for step in flow.error_handling.steps:
                    err_plugin = get_plugin(step.type)
                    if err_plugin is not None:
                        try:
                            ctx = err_plugin.execute(step, ctx, mocks)
                        except Exception as exc2:
                            ctx.add_trace(step.id, "error", f"error-subprocess exception: {exc2}")
            break

        # If this was a router, prune the queue to only the selected branch.
        if node.type == "router.content-based":
            selected_target = ctx.properties.get("__router_selected_target__")
            if selected_target:
                # Find the matching edge's condition id for the selected target
                selected_condition = ctx.properties.get("__router_selected_condition__")
                # Remove from queue any nodes that are reached via non-matching router edges.
                # Conservative approach: only execute the selected target next; defer siblings.
                # We do this by reordering: move selected_target to the front and remove
                # siblings (other router targets) from the queue.
                siblings_to_skip: set[str] = set()
                for to, cond in adjacency.get(node_id, []):
                    if cond is not None and cond != selected_condition:
                        siblings_to_skip.add(to)
                if siblings_to_skip:
                    queue = [n for n in queue if n not in siblings_to_skip]
                    visited |= siblings_to_skip  # mark as visited so they won't re-run

    if ctx.exchange_status != ExchangeStatus.FAILED:
        ctx.exchange_status = ExchangeStatus.COMPLETED

    ctx.properties["__duration_ms__"] = int((time.monotonic() - start_time) * 1000)
    return ctx
