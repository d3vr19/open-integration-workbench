"""B2 — the Experiment Engine (roadmap handoff 2026-09-02, the existential one).

Turns "smart harness + human bisection" into "system that learns", mechanically:

    green artifact ──► variant ladder (single-variable mutations)
                   ──► oracle verdict per rung (deploy→poll→message→MPL)
                   ──► verdict flips isolate the minimal delta
                   ──► delta becomes a LAW in a YAML registry (evidence attached)
                   ──► registry consumed by oiw validate / assembler / prompts

This module defines the experiment RECORD types + the ddmin-style ladder
logic — all pure and local. Tenant execution (cool-down-governed, operator
approved) lives in runner.py; the registry in registry.py.

The METHOD this engine automates (blood-tested across p5-p6):
    harvest reference bytes → mirror verbatim → unit tests → live oracle
    single-variable proof → law to registry → parity case → commit.

Ladder kinds (conv1–conv10 vocabulary):
    drop   — remove one node (does the chain still run without it?)
    move   — move one node to another position (does placement matter?)
    swap   — replace one node's type with another piece (does the type matter?)
    insert — insert one piece before/after another (what must precede what?)

The converter law (conv1–conv10, 2026-09-02) is the acceptance corpus:
the engine MUST re-derive it from the recorded rungs — see
tests/learn/test_experiment.py::test_rederive_converter_law.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..project import Entrypoint, FlowEdge, FlowNode, IntegrationFlow

# Verdict vocabulary — matches CalibrationReport.final_status + message leg.
VERDICT_GREEN = "GREEN"  # STARTED + message 200 + all MPL COMPLETED
VERDICT_RED = "RED"  # runtime-start ERROR / message failure / MPL FAILED
VERDICT_SKIPPED = "SKIPPED"  # not run (budget, cool-down, invalid variant)


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _deep_copy_flow(flow: IntegrationFlow) -> IntegrationFlow:
    """Copy a flow with fresh node/edge objects (dataclasses are shallow)."""
    return IntegrationFlow(
        id=flow.id,
        name=flow.name,
        version=flow.version,
        entrypoints=[
            Entrypoint(id=e.id, type=e.type, config=dict(e.config), fidelity=e.fidelity)
            for e in flow.entrypoints
        ],
        nodes=[
            FlowNode(id=n.id, type=n.type, config=dict(n.config), fidelity=n.fidelity) for n in flow.nodes
        ],
        edges=[FlowEdge(from_=e.from_, to=e.to, condition=e.condition) for e in flow.edges],
        error_handling=flow.error_handling,
        extensions=dict(flow.extensions),
        labels=dict(flow.labels),
        generated_by=flow.generated_by,
        source_path=flow.source_path,
        diagram=flow.diagram,
    )


def execution_order(flow: IntegrationFlow) -> list[str]:
    """Deterministic execution order: entrypoints, then BFS over edges.

    Same shape as learn/loop._execution_order (insight workflow form).
    """
    seen: list[str] = []
    queue: list[str] = [e.id for e in flow.entrypoints]
    visited: set[str] = set()
    while queue:
        nid = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        seen.append(nid)
        for edge in flow.edges:
            if edge.from_ == nid and edge.to not in visited:
                queue.append(edge.to)
    for n in sorted(flow.nodes, key=lambda n: n.id):
        if n.id not in visited:
            seen.append(n.id)
    return seen


@dataclass
class Rung:
    """One single-variable variant of the baseline flow.

    `kind` ∈ {drop, move, swap, insert}. `target` identifies the mutated
    node(s); `detail` carries kind-specific payload. The variant is
    materialized lazily via `mutate()` so the ladder is cheap to build
    and inspect (dry-run) before any oracle call.
    """

    rung_id: str
    kind: str  # drop | move | swap | insert
    target: str  # node id the mutation centers on
    detail: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    verdict: str = VERDICT_SKIPPED  # filled by the runner
    evidence: dict[str, Any] = field(default_factory=dict)  # oracle report digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "rungId": self.rung_id,
            "kind": self.kind,
            "target": self.target,
            "detail": self.detail,
            "rationale": self.rationale,
            "verdict": self.verdict,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Rung:
        return cls(
            rung_id=d["rungId"],
            kind=d["kind"],
            target=d["target"],
            detail=d.get("detail") or {},
            rationale=d.get("rationale") or "",
            verdict=d.get("verdict") or VERDICT_SKIPPED,
            evidence=d.get("evidence") or {},
        )


@dataclass
class ExperimentRecord:
    """One experiment campaign over a baseline (green) artifact.

    Append-only; the law-derivation step consumes completed records.
    """

    experiment_id: str
    baseline_flow_id: str
    hypothesis: str  # what the campaign is trying to isolate
    created_at: str = field(default_factory=_now_iso)
    rungs: list[Rung] = field(default_factory=list)
    baseline_verdict: str = VERDICT_SKIPPED
    status: str = "draft"  # draft | running | complete | aborted

    def to_dict(self) -> dict[str, Any]:
        return {
            "experimentId": self.experiment_id,
            "baselineFlowId": self.baseline_flow_id,
            "hypothesis": self.hypothesis,
            "createdAt": self.created_at,
            "baselineVerdict": self.baseline_verdict,
            "status": self.status,
            "rungs": [r.to_dict() for r in self.rungs],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExperimentRecord:
        return cls(
            experiment_id=d["experimentId"],
            baseline_flow_id=d["baselineFlowId"],
            hypothesis=d.get("hypothesis") or "",
            created_at=d.get("createdAt") or "",
            baseline_verdict=d.get("baselineVerdict") or VERDICT_SKIPPED,
            status=d.get("status") or "draft",
            rungs=[Rung.from_dict(r) for r in d.get("rungs") or []],
        )

    def rung(self, rung_id: str) -> Rung | None:
        return next((r for r in self.rungs if r.rung_id == rung_id), None)


# ---------------------------------------------------------------------------
# Variant materialization (pure flow surgery — no I/O)
# ---------------------------------------------------------------------------


def _node_types(flow: IntegrationFlow) -> list[str]:
    return [n.type for n in flow.nodes]


def _find_node(flow: IntegrationFlow, node_id: str) -> FlowNode | None:
    return next((n for n in flow.nodes if n.id == node_id), None)


def _remove_node(flow: IntegrationFlow, node_id: str) -> IntegrationFlow:
    """Remove a node and splice its edges (pred -> node -> succ)."""
    preds = [e.from_ for e in flow.edges if e.to == node_id]
    succs = [e.to for e in flow.edges if e.from_ == node_id]
    mutated = _deep_copy_flow(flow)
    mutated.nodes = [n for n in mutated.nodes if n.id != node_id]
    mutated.edges = [e for e in mutated.edges if e.from_ != node_id and e.to != node_id]
    for p in preds:
        for s in succs:
            mutated.edges.append(FlowEdge(from_=p, to=s))
    return mutated


def _relink_positions(flow: IntegrationFlow, order: list[str]) -> IntegrationFlow:
    """Re-chain nodes into the given linear order (entrypoint(s) stay first)."""
    mutated = _deep_copy_flow(flow)
    entry_ids = [e.id for e in mutated.entrypoints]
    body = [nid for nid in order if nid not in entry_ids]
    chain = entry_ids + body
    mutated.edges = [FlowEdge(from_=chain[i], to=chain[i + 1]) for i in range(len(chain) - 1)]
    return mutated


def materialize_variant(
    baseline: IntegrationFlow,
    rung: Rung,
    *,
    piece_provider: dict[str, dict[str, Any]] | None = None,
) -> IntegrationFlow:
    """Apply one rung's mutation to a copy of the baseline flow.

    `piece_provider` maps node type -> default config (the proven piece
    library) — required by insert/swap so variants use LIVE-SAFE configs,
    never invented ones.
    """
    pieces = piece_provider or {}
    if rung.kind == "drop":
        return _remove_node(baseline, rung.target)
    if rung.kind == "move":
        order = [nid for nid in execution_order(baseline) if nid != rung.target]
        pos = max(0, min(int(rung.detail.get("toPosition", 0)), len(order)))
        order.insert(pos, rung.target)
        return _relink_positions(baseline, order)
    if rung.kind == "swap":
        node = _find_node(baseline, rung.target)
        if node is None:
            raise ValueError(f"swap target {rung.target!r} not found")
        new_type = str(rung.detail.get("newType", ""))
        if new_type not in pieces:
            raise ValueError(f"swap type {new_type!r} is not a proven piece")
        mutated = _deep_copy_flow(baseline)
        for n in mutated.nodes:
            if n.id == rung.target:
                n.type = new_type
                n.config = dict(pieces[new_type])
        return mutated
    if rung.kind == "insert":
        new_type = str(rung.detail.get("newType", ""))
        if new_type not in pieces:
            raise ValueError(f"insert type {new_type!r} is not a proven piece")
        order = execution_order(baseline)
        after = rung.detail.get("after", rung.target)
        pos = order.index(after) + 1 if after in order else len(order)
        mutated = _relink_positions(baseline, order)
        new_id = f"exp-insert-{new_type.replace('.', '-')}-{rung.rung_id[-6:]}"
        mutated.nodes.append(
            FlowNode(
                id=new_id,
                type=new_type,
                config=dict(pieces[new_type]),
                fidelity="compatible-subset",
            )
        )
        # splice into the linear chain
        mutated.edges = []
        chain = [e.id for e in mutated.entrypoints] + [
            nid for nid in order if nid not in {e.id for e in mutated.entrypoints}
        ]
        chain.insert(pos, new_id)
        mutated.edges = [FlowEdge(from_=chain[i], to=chain[i + 1]) for i in range(len(chain) - 1)]
        return mutated
    raise ValueError(f"unknown rung kind {rung.kind!r}")


# ---------------------------------------------------------------------------
# Ladder generation (ddmin-style, breadth-first over single-variable space)
# ---------------------------------------------------------------------------


def generate_ladder(
    baseline: IntegrationFlow,
    *,
    hypothesis: str,
    kinds: tuple[str, ...] = ("drop", "move", "insert"),
    swap_types: tuple[str, ...] = (),
    insert_types: tuple[str, ...] = (),
    max_rungs: int = 40,
) -> ExperimentRecord:
    """Build the single-variable variant ladder for a baseline flow.

    Every rung mutates EXACTLY ONE thing vs the baseline (ddmin discipline:
    one variable per deploy; the conv1–conv10 corpus was run this way by
    hand). The ladder is deterministic and ordered cheapest-first:

        drop (n) → move (n·positions) → insert (n·types) → swap (n·types)

    Entrypoints are never dropped/moved (one exchange pattern per artifact
    is a blood law — the ladder must not test settled laws).
    """
    record = ExperimentRecord(
        experiment_id=f"exp-{uuid.uuid4().hex[:10]}",
        baseline_flow_id=baseline.id,
        hypothesis=hypothesis,
    )
    body_ids = [nid for nid in execution_order(baseline) if nid not in {e.id for e in baseline.entrypoints}]
    n_rungs = 0

    if "drop" in kinds:
        for nid in body_ids:
            if n_rungs >= max_rungs:
                break
            node = _find_node(baseline, nid)
            if node is None:
                continue
            record.rungs.append(
                Rung(
                    rung_id=f"r{n_rungs + 1}-drop-{nid}",
                    kind="drop",
                    target=nid,
                    rationale=f"drop {node.type} — does the chain need it?",
                )
            )
            n_rungs += 1

    if "move" in kinds:
        for nid in body_ids:
            if n_rungs >= max_rungs:
                break
            for pos in range(len(body_ids)):
                if pos == body_ids.index(nid):
                    continue
                record.rungs.append(
                    Rung(
                        rung_id=f"r{n_rungs + 1}-move-{nid}-to{pos}",
                        kind="move",
                        target=nid,
                        detail={"toPosition": pos},
                        rationale=f"move node to position {pos} — does placement matter?",
                    )
                )
                n_rungs += 1
                if n_rungs >= max_rungs:
                    break

    if "insert" in kinds and insert_types:
        for new_type in insert_types:
            if n_rungs >= max_rungs:
                break
            for nid in body_ids:
                record.rungs.append(
                    Rung(
                        rung_id=f"r{n_rungs + 1}-insert-{new_type}-after-{nid}",
                        kind="insert",
                        target=nid,
                        detail={"newType": new_type, "after": nid},
                        rationale=(f"insert {new_type} after {nid} — what must precede what?"),
                    )
                )
                n_rungs += 1
                if n_rungs >= max_rungs:
                    break

    if "swap" in kinds and swap_types:
        for nid in body_ids:
            if n_rungs >= max_rungs:
                break
            node = _find_node(baseline, nid)
            if node is None:
                continue
            for new_type in swap_types:
                if new_type == node.type:
                    continue
                record.rungs.append(
                    Rung(
                        rung_id=f"r{n_rungs + 1}-swap-{nid}-{new_type}",
                        kind="swap",
                        target=nid,
                        detail={"newType": new_type},
                        rationale=f"swap {node.type} for {new_type} — does the type matter?",
                    )
                )
                n_rungs += 1
                if n_rungs >= max_rungs:
                    break

    record.status = "draft"
    return record


# ---------------------------------------------------------------------------
# Law derivation (the verdict-flip analysis — pure)
# ---------------------------------------------------------------------------


@dataclass
class LawCandidate:
    """A minimal green→red delta isolated by the ladder.

    `law` is the human/LLM-readable statement; `predicate` is the
    machine-checkable form consumed by validators/law_checks.py (see
    LawRecord.predicate for the shapes). `evidence` cites rungs:
    the green rung (or baseline) vs the red rung that differs by exactly
    the one mutation.
    """

    law_id: str
    statement: str
    scope: str  # e.g. "converter.json-to-xml" or "flow.topology"
    kind: str  # drop | move | swap | insert (the flip's mutation kind)
    green_rungs: list[str] = field(default_factory=list)
    red_rungs: list[str] = field(default_factory=list)
    confidence: float = 0.0  # fraction of corroborating rungs
    predicate: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "lawId": self.law_id,
            "statement": self.statement,
            "scope": self.scope,
            "kind": self.kind,
            "evidence": {
                "greenRungs": self.green_rungs,
                "redRungs": self.red_rungs,
            },
            "confidence": self.confidence,
            "predicate": self.predicate,
        }


def derive_laws(record: ExperimentRecord) -> list[LawCandidate]:
    """Analyze a completed experiment record for verdict flips.

    A LAW candidate is isolated when:
      - a rung is RED while the baseline is GREEN (the mutation broke a
        working chain — the mutated variable is load-bearing), or
      - a rung is GREEN where the corresponding class of variants was
        expected red (placement freedom — ALSO a law, positive form).

    Single-variable discipline guarantees the delta IS the law (whatever
    else differs, exactly one mutation separates green from red).
    """
    if record.baseline_verdict != VERDICT_GREEN:
        return []  # laws are only derived from a green baseline

    candidates: list[LawCandidate] = []
    red = [r for r in record.rungs if r.verdict == VERDICT_RED]
    green_rungs = [r for r in record.rungs if r.verdict == VERDICT_GREEN]

    for r in red:
        # The statement shape depends on the mutation kind.
        if r.kind == "drop":
            statement = f"dropping {r.target} breaks the chain — the step is load-bearing"
        elif r.kind == "move":
            statement = f"position of {r.target} is load-bearing " f"(moved to {r.detail.get('toPosition')})"
        elif r.kind == "swap":
            statement = f"{r.target} cannot be replaced by {r.detail.get('newType')}"
        elif r.kind == "insert":
            statement = (
                f"inserting {r.detail.get('newType')} after {r.detail.get('after')} " "breaks the chain"
            )
        else:
            statement = f"mutation {r.kind} on {r.target} breaks the chain"
        # Corroboration: same-kind mutations on the same target that stayed
        # green bound the law's scope (it's not "any change is fatal").
        corroborating_green = [g.rung_id for g in green_rungs if g.kind == r.kind and g.target == r.target]
        candidates.append(
            LawCandidate(
                law_id=f"law-{r.rung_id}",
                statement=statement,
                scope=_scope_for(r),
                kind=r.kind,
                green_rungs=[record.experiment_id] if not corroborating_green else corroborating_green[:1],
                red_rungs=[r.rung_id],
                confidence=1.0 if corroborating_green else 0.5,
                predicate=_predicate_for(r, record, corroborating_green),
            )
        )
    return candidates


def _predicate_for(
    rung: Rung,
    record: ExperimentRecord,
    corroborating_green: list[str],
) -> dict[str, Any] | None:
    """Machine-checkable law form, when the evidence pins one.

    MOVE rungs with a green corroboration pin a placement law precisely:
    the red position(s) vs the green position(s) of the SAME target. If
    every green position is > every red position, the step must sit
    AFTER some predecessor; the immediate green predecessor common to
    the green rungs becomes the required predecessor. The engine types
    the predecessor from the baseline chain (targetType evidence).
    """
    if rung.kind != "move" or not corroborating_green:
        return None
    green_by_id = {r.rung_id: r for r in record.rungs if r.verdict == VERDICT_GREEN}
    red_positions = [int(rung.detail.get("toPosition", -1))]
    green_positions = [
        int(green_by_id[rid].detail.get("toPosition", -1))
        for rid in corroborating_green
        if rid in green_by_id
    ]
    if not green_positions or min(green_positions) <= max(red_positions):
        return None  # not a clean before/after split — advisory only
    ev_type = (rung.evidence or {}).get("targetType")
    if not ev_type:
        return None
    return {
        "type": "requires-position-after",
        "node": ev_type,
        "redPositions": sorted(set(red_positions)),
        "greenPositions": sorted(set(green_positions)),
    }


def _scope_for(rung: Rung) -> str:
    """Best-effort scope for a law candidate from rung metadata."""
    new_type = rung.detail.get("newType")
    if rung.kind in ("insert", "swap") and new_type:
        return str(new_type)
    if rung.target:
        # node-type scope is preferred; the runner stamps evidence with
        # the target's type so laws land on component types, not ids.
        ev_type = (rung.evidence or {}).get("targetType")
        if ev_type:
            return str(ev_type)
    return "flow.topology"


__all__ = [
    "VERDICT_GREEN",
    "VERDICT_RED",
    "VERDICT_SKIPPED",
    "ExperimentRecord",
    "LawCandidate",
    "Rung",
    "derive_laws",
    "execution_order",
    "generate_ladder",
    "materialize_variant",
]
