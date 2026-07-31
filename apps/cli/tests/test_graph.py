"""Tests for the semantic graph validator (spec §9.2 step 2, §14)."""

from __future__ import annotations

from oiw.project import Entrypoint, ErrorSubprocess, FlowEdge, FlowNode, IntegrationFlow
from oiw.validators.graph import validate_flow_graph

_SENTINEL = object()


def _make_flow(
    *,
    nodes: list[FlowNode] | object = _SENTINEL,
    edges: list[FlowEdge] | object = _SENTINEL,
    entrypoints: list[Entrypoint] | object = _SENTINEL,
) -> IntegrationFlow:
    return IntegrationFlow(
        id="test-flow",
        name="Test Flow",
        version=1,
        entrypoints=entrypoints
        if isinstance(entrypoints, list)
        else [Entrypoint(id="in", type="sender.http", config={})],
        nodes=nodes if isinstance(nodes, list) else [FlowNode(id="n1", type="log.message", config={})],
        edges=edges if isinstance(edges, list) else [FlowEdge(from_="in", to="n1")],
        error_handling=ErrorSubprocess(steps=[FlowNode(id="err", type="log.message", config={})]),
    )


def test_valid_flow_has_no_errors() -> None:
    flow = _make_flow()
    errors, warnings = validate_flow_graph(flow)
    assert errors == [], f"unexpected errors: {errors}"


def test_missing_entrypoint_errors() -> None:
    flow = _make_flow(entrypoints=[])
    errors, _ = validate_flow_graph(flow)
    assert any("no entrypoint" in e for e in errors)


def test_missing_nodes_errors() -> None:
    flow = _make_flow(nodes=[], edges=[])
    errors, _ = validate_flow_graph(flow)
    assert any("no nodes" in e for e in errors)


def test_dangling_edge_errors() -> None:
    flow = _make_flow(
        nodes=[FlowNode(id="n1", type="log.message", config={})],
        edges=[FlowEdge(from_="in", to="n1"), FlowEdge(from_="n1", to="nonexistent")],
    )
    errors, _ = validate_flow_graph(flow)
    assert any("unknown 'to'" in e for e in errors)


def test_duplicate_node_ids_error() -> None:
    flow = _make_flow(
        nodes=[
            FlowNode(id="n1", type="log.message", config={}),
            FlowNode(id="n1", type="log.message", config={}),
        ],
        edges=[FlowEdge(from_="in", to="n1")],
    )
    errors, _ = validate_flow_graph(flow)
    assert any("duplicate" in e for e in errors)


def test_unreachable_node_errors() -> None:
    flow = _make_flow(
        nodes=[
            FlowNode(id="n1", type="log.message", config={}),
            FlowNode(id="orphan", type="log.message", config={}),
        ],
        edges=[FlowEdge(from_="in", to="n1")],
    )
    errors, _ = validate_flow_graph(flow)
    assert any("unreachable" in e for e in errors)


def test_directed_cycle_detected() -> None:
    flow = _make_flow(
        nodes=[
            FlowNode(id="a", type="log.message", config={}),
            FlowNode(id="b", type="log.message", config={}),
        ],
        edges=[
            FlowEdge(from_="in", to="a"),
            FlowEdge(from_="a", to="b"),
            FlowEdge(from_="b", to="a"),
        ],
    )
    errors, _ = validate_flow_graph(flow)
    assert any("cycle" in e for e in errors), f"expected cycle error in: {errors}"
