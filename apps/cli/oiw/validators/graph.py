"""Semantic graph validation.

Spec ref: §9.2 step 2 (validate graph before execution), §14 (validation engine).
Checks:
  - Every flow has at least one entrypoint and at least one node.
  - All edge endpoints reference existing nodes.
  - The graph is weakly connected (every node reachable from an entrypoint).
  - No unbounded cycles (we allow only the explicitly modelled error subprocess
    loop-back, not arbitrary cycles in the main flow).
  - Every node declares a fidelity level (defaults to 'simulated' if omitted).
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable

from ..project import FlowEdge, IntegrationFlow


def validate_flow_graph(flow: IntegrationFlow) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for the flow graph."""
    errors: list[str] = []
    warnings: list[str] = []

    if not flow.entrypoints:
        errors.append(f"OIW-E001: flow '{flow.id}' has no entrypoint")
    if not flow.nodes:
        errors.append(f"OIW-E001: flow '{flow.id}' has no nodes")

    node_ids = {n.id for n in flow.nodes}
    entry_ids = {e.id for e in flow.entrypoints}
    all_ids = node_ids | entry_ids

    # Edge endpoint validation
    for edge in flow.edges:
        if edge.from_ not in all_ids:
            errors.append(f"OIW-E001: edge references unknown 'from' node '{edge.from_}' in flow '{flow.id}'")
        if edge.to not in all_ids:
            errors.append(f"OIW-E001: edge references unknown 'to' node '{edge.to}' in flow '{flow.id}'")

    # Duplicate node IDs
    seen: set[str] = set()
    for n in flow.nodes:
        if n.id in seen:
            errors.append(f"OIW-E001: duplicate node id '{n.id}' in flow '{flow.id}'")
        seen.add(n.id)

    # Weakly connected check via BFS over an undirected view
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in flow.edges:
        adjacency[edge.from_].add(edge.to)
        adjacency[edge.to].add(edge.from_)
    # Entrypoints connect to their first downstream node via implicit edge
    # (modelled explicitly in IR; if missing, we warn).
    for entry in flow.entrypoints:
        downstream = adjacency.get(entry.id)
        if not downstream:
            warnings.append(f"OIW-W008: entrypoint '{entry.id}' has no outgoing edge in flow '{flow.id}'")

    if all_ids and entry_ids:
        start = next(iter(entry_ids))
        visited: set[str] = set()
        queue: deque[str] = deque([start])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            for nxt in adjacency.get(current, ()):
                if nxt not in visited:
                    queue.append(nxt)
        unreachable = all_ids - visited
        if unreachable:
            for n_id in sorted(unreachable):
                errors.append(
                    f"OIW-E001: node '{n_id}' is unreachable from any entrypoint in flow '{flow.id}'"
                )

    # Cycle detection in the directed graph (main flow only; error subprocess excluded).
    cycle = _find_directed_cycle(entry_ids, flow.edges)
    if cycle:
        errors.append(f"OIW-E001: unbounded cycle detected in flow '{flow.id}': {' -> '.join(cycle)}")

    # Fidelity presence (defaults applied by loader; warn if missing in source)
    for n in flow.nodes:
        if not n.fidelity:
            warnings.append(
                f"OIW-W008: node '{n.id}' (type={n.type}) has no fidelity label in flow '{flow.id}'"
            )

    return errors, warnings


def _find_directed_cycle(entry_ids: Iterable[str], edges: Iterable[FlowEdge]) -> list[str] | None:
    """Detect a directed cycle reachable from any entrypoint. Returns the cycle path or None."""
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adjacency[edge.from_].append(edge.to)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(lambda: WHITE)
    parent: dict[str, str | None] = {}

    def dfs(start: str) -> list[str] | None:
        stack = [(start, iter(adjacency.get(start, ())))]
        color[start] = GRAY
        while stack:
            node, neighbors = stack[-1]
            advanced = False
            for nxt in neighbors:
                if color[nxt] == GRAY:
                    # Found a cycle: reconstruct from `node` back to `nxt`.
                    cycle = [nxt, node]
                    cur = parent.get(node)
                    while cur is not None and cur != nxt:
                        cycle.append(cur)
                        cur = parent.get(cur)
                    cycle.reverse()
                    return cycle
                if color[nxt] == WHITE:
                    color[nxt] = GRAY
                    parent[nxt] = node
                    stack.append((nxt, iter(adjacency.get(nxt, ()))))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
        return None

    for entry in entry_ids:
        if color[entry] == WHITE:
            cycle = dfs(entry)
            if cycle:
                return cycle
    return None
