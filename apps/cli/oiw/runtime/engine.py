"""Execution engine.

Spec ref: §9.2 (Execution Engine).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from ..project import FlowNode, IntegrationFlow
from .context import ExchangeStatus, MessageContext, TraceEntry
from .steps.base import get_plugin

# Trace payload preview limit — enough to inspect, never a full-body copy
# in the trace stream (payload data still lives in the exchange itself).
_TRACE_PREVIEW_CHARS = 2000


def _preview(body: bytes | str | None) -> str | None:
    """Bounded text preview of an exchange body for trace entries."""
    if body is None:
        return None
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
    if len(text) > _TRACE_PREVIEW_CHARS:
        return text[:_TRACE_PREVIEW_CHARS] + f"… (+{len(text) - _TRACE_PREVIEW_CHARS} chars)"
    return text


def _public_properties(ctx: MessageContext) -> dict[str, Any]:
    """Exchange properties without the __-prefixed engine internals."""
    return {k: v for k, v in ctx.properties.items() if not str(k).startswith("__")}


class ExecutionError(Exception):
    """Raised when a flow cannot be executed."""


# Marker embedded in real-engine refusals so callers (parity runner, tests)
# can distinguish "sim cannot even claim this step" from a genuine transform
# failure (p5-p6-plan.md §6, session 9).
REAL_UNSUPPORTED_MARKER = "OIW-REAL-UNSUPPORTED"

# Endpoint families stay mockable in real mode: their local behavior is the
# world-dynamics seam (P5b), not a silent stub of transform logic.
_ENDPOINT_PREFIXES = ("sender.", "receiver.")


# A trace callback receives each TraceEntry as it's produced.
# Spec §9.2 step 8: "Capture structured trace and stream via WebSocket to UI."
TraceCallback = Callable[[TraceEntry, MessageContext], None]


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
    trace_callback: TraceCallback | None = None,
    engine: str = "simulated",
) -> MessageContext:
    """Execute a flow against the given input. Returns the final MessageContext.

    Spec §9.2 step 1: compile IR into an ExecutionPlan (topological sort).
    Spec §9.2 step 2: validate graph before execution.
    Spec §9.2 step 4: record input/output snapshot per node.
    Spec §9.2 step 7: enforce timeouts (TODO) and memory quotas (TODO).
    Spec §9.2 step 8: capture structured trace and stream via WebSocket to UI.

    Args:
        engine: "simulated" (default) executes plugins as-is; "real"
            (P5a-M2) additionally refuses — loudly, via exchange FAILED +
            REAL_UNSUPPORTED_MARKER — any executed NON-endpoint step whose
            plugin declares fidelity="simulated". Silent stubs must never
            pollute parity measurement (§0 honesty rule).
        trace_callback: If provided, called with each TraceEntry as it's
            produced (before the entry is appended to ctx.trace). This
            enables real-time streaming to WebSocket clients.
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

    # Wrap add_trace so the callback fires on every trace event (spec §9.2 step 8)
    if trace_callback is not None:
        _original_add_trace = ctx.add_trace

        def _streaming_add_trace(node_id: str, direction: str, summary: str, **extra: Any) -> None:
            entry = TraceEntry(
                node_id=node_id,
                timestamp=time.time(),
                direction=direction,
                summary=summary,
                body_preview=extra.get("body_preview"),
                headers=extra.get("headers"),
            )
            trace_callback(entry, ctx)
            _original_add_trace(node_id, direction, summary, **extra)

        ctx.add_trace = _streaming_add_trace  # type: ignore[method-assign]

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
            # Trace capture seam (FIGAF-style debugging, spec §9.2 step 4):
            # snapshot the exchange around every step so the workbench can
            # show in/out payloads, headers, properties, and durations per
            # node. Snapshots are bounded (no full-body copies beyond a
            # preview limit) so tracing stays cheap.
            ctx.add_trace(
                node_id,
                "enter",
                f"enter {node.type}",
                body_preview=_preview(ctx.body),
                headers=dict(ctx.headers),
                properties=_public_properties(ctx),
            )
            step_t0 = time.monotonic()
            ctx = plugin.execute(node, ctx, mocks)
            step_ms = int((time.monotonic() - step_t0) * 1000)
            ctx.add_trace(
                node_id,
                "exit",
                f"exit {node.type} ({step_ms}ms)",
                body_preview=_preview(ctx.body),
                headers=dict(ctx.headers),
                properties=_public_properties(ctx),
                duration_ms=step_ms,
            )
        except Exception as exc:
            ctx.exchange_status = ExchangeStatus.FAILED
            ctx.exception = exc
            ctx.add_trace(
                node_id,
                "error",
                f"exception: {exc}",
                body_preview=_preview(ctx.body),
                headers=dict(ctx.headers),
                properties=_public_properties(ctx),
                exception_type=type(exc).__name__,
            )
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
        # Real-engine fidelity audit (P5a-M2): only executed nodes are
        # audited, endpoints are exempt (mock seam). A stub that executed
        # silently would corrupt parity measurement — refuse instead.
        offenders: list[str] = []
        if engine == "real":
            # Audit every DECLARED node (plan order), not just executed ones:
            # the tenant compiles the whole bundle — an unreachable stub is
            # still a lie waiting for a different input.
            for node_id in plan.order:
                node = node_map.get(node_id)
                if node is None or node.type.startswith(_ENDPOINT_PREFIXES):
                    continue
                plugin = get_plugin(node.type)
                if plugin is None:
                    continue
                if plugin.compatibility().get("fidelity") == "simulated":
                    offenders.append(f"{node_id} ({node.type})")
        if offenders:
            detail = (
                f"{REAL_UNSUPPORTED_MARKER}: real engine refuses simulated-fidelity "
                f"step(s): {', '.join(sorted(offenders))}. Implement true logic "
                "or run with --engine simulated."
            )
            ctx.exchange_status = ExchangeStatus.FAILED
            ctx.exception = ExecutionError(detail)
            ctx.add_trace("__engine__", "error", detail)
        else:
            ctx.exchange_status = ExchangeStatus.COMPLETED

    ctx.properties["__duration_ms__"] = int((time.monotonic() - start_time) * 1000)

    # Emit a final completion event for streaming clients (spec §9.2 step 8)
    if trace_callback is not None:
        final_entry = TraceEntry(
            node_id="__flow__",
            timestamp=time.time(),
            direction="complete",
            summary=f"flow {ctx.exchange_status} in {ctx.properties['__duration_ms__']}ms",
        )
        trace_callback(final_entry, ctx)

    return ctx
