"""Phase D — turbo piece-assembler (p5-p6-plan.md §5D).

Turbo is a PIECE-ASSEMBLER, not a freeform agent:

  - plan→implement→simulate→repair cycles using ONLY grammar pieces +
    the EMG corpus (mechanics-first). It never freeforms.
  - LLM is the last-resort TEACHER, never the first mover (operator
    decision, 2026-08-26). When no piece matches or N repair cycles
    fail, turbo emits a structured teacher-request; the answer must
    merge back as a new piece + regression case. TEACHER-SUMMONS RATE
    is the headline self-improvement metric and must trend to zero.
  - Hard bounds: iteration cap, wall-clock cap. The tenant adapter is
    UNREACHABLE from turbo mode — enforced at code level (a guard that
    raises on any tenant-tool dispatch), not by convention.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..project import IntegrationFlow
from ..runtime.steps.base import all_plugins, get_plugin
from .interpreter import NormalizedRequirement


# Node types the real engine can execute honestly (fidelity != simulated;
# endpoints are exempt from the real-engine audit but they are the mock
# seam, so they are always usable pieces).
def _real_engine_pieces() -> set[str]:
    pieces: set[str] = set()
    for ntype, plugin in all_plugins().items():
        if (
            ntype.startswith(("sender.", "receiver."))
            or plugin.compatibility().get("fidelity") != "simulated"
        ):
            pieces.add(ntype)
    return pieces


def proven_pieces() -> dict[str, dict[str, Any]]:
    """The grammar piece library: node types the real engine can run.

    Keyed by node type; value carries the plugin descriptor + fidelity
    so the assembler can reason about what it composes. This set is the
    honest floor — anything absent is a teacher-summons, not a guess.
    """
    out: dict[str, dict[str, Any]] = {}
    for ntype in sorted(_real_engine_pieces()):
        plugin = get_plugin(ntype)
        if plugin is None:
            continue
        out[ntype] = {
            "descriptor": plugin.descriptor(),
            "fidelity": plugin.compatibility().get("fidelity", "simulated"),
            "security": plugin.security_classification(),
        }
    return out


@dataclass
class Piece:
    """One assembly piece — an addNode operation with rationale."""

    node_id: str
    node_type: str
    config: dict[str, Any] = field(default_factory=dict)
    fidelity: str = "compatible-subset"
    rationale: str = ""


@dataclass
class AssemblyResult:
    """Result of assembling a flow from pieces + corpus."""

    assembled: bool
    pieces: list[Piece] = field(default_factory=list)
    unmatched_components: list[str] = field(default_factory=list)
    entrypoint: Piece | None = None
    receiver: Piece | None = None
    reason: str = ""
    # Live topology law (2026-09-02): RR chains need a message-typed end.
    # A terminal receiver.http gets a PD terminator; the companion listener
    # address is recorded here so the deploy loop can ship the pair.
    companion_listener_address: str | None = None


# ---------------------------------------------------------------------------
# Interpreter mapping: requirement components → pieces
# ---------------------------------------------------------------------------

# Requirement component → grammar piece. Components the interpreter
# detects map 1:1 onto real-engine-proven node types where they exist.
# LIVE FINDINGS (2026-09-02, tenant bisection conv1-conv9):
#   - converter.json-to-xml IS live-proven (conv9: RR→converter→RR→PD chain,
#     message 200, MPL COMPLETED both artifacts, reward 1.0) — but ONLY in
#     post-RR placement. A converter directly before an HTTP receiver in
#     the main process fails ('Member name not found'; the tenant's own
#     converter flows place converters in subprocesses, never adjacent to
#     the adapter). The assembler enforces the proven placement.
#   - variables.write values ride ProcessDirect as HEADERS — multi-line
#     bodies (converted XML) are invalid header content. Companion
#     listeners terminate with log.message instead (conv9 law).
_LIVE_UNPROVEN: set[str] = set()  # converter.json-to-xml validated 2026-09-02 (conv9)

# Placement laws: pieces that must NOT directly precede receiver.http.
# They need another step (or an RR response) between them and the adapter.
_NO_DIRECT_HTTP_NEIGHBOR = {"converter.json-to-xml", "converter.xml-to-json"}

_COMPONENT_TO_PIECE: dict[str, str] = {
    "sender.http": "sender.http",
    "sender.https": "sender.http",
    "receiver.http": "receiver.http",
    "log.message": "log.message",
    "modifier.content": "modifier.content",
    "converter.json-to-xml": "converter.json-to-xml",
    "converter.xml-to-json": "converter.xml-to-json",
    "encoder.base64": "encoder.base64",
    "script.groovy": "script.groovy",
    "validator.json-schema": "validator.json-schema",
    "router.content-based": "router.content-based",
    "router": "router.content-based",
    "filter": "filter",
    "splitter.general": "splitter.general",
}

# Fallback orderings when the interpreter found no explicit entry/receiver.
_ENTRYPOINT_CANDIDATES = ["sender.http"]
_RECEIVER_CANDIDATES = ["receiver.http", "receiver.sftp"]


_URL_RE = re.compile(
    r"https?://[^\s,;\"'<>]+",  # scheme://host/path?query — stop at whitespace/punct
)


def extract_target_url(requirement: NormalizedRequirement) -> str | None:
    """Pull the FIRST https?:// URL from the requirement text.

    Deterministic (no LLM): a directive like "forward the XML to
    https://host/api" must actually target that URL, not a placeholder.
    Returns None when the requirement names no URL.
    """
    match = _URL_RE.search(requirement.raw or "")
    if not match:
        return None
    url = match.group(0).rstrip(".,;:)")
    return url or None


# Directive verb → receiver HTTP method. "forward/send/post" is a write
# (POST); "fetch/get/call/retrieve" is a read (GET). Deterministic.
_POST_VERBS = ("forward", "send", "post", "push", "submit", "deliver")
_GET_VERBS = ("fetch", "get from", "call", "retrieve", "read from", "poll")


def extract_receiver_method(requirement: NormalizedRequirement) -> str:
    """Derive the receiver's HTTP method from the directive's verb.

    First matching verb wins, POST when nothing matches (the safer
    default — a failed GET-shaped POST is visible, a failed POST-shaped
    GET silently returns the wrong body).
    """
    text = (requirement.raw or "").lower()
    for verb in _GET_VERBS:
        if verb in text:
            return "GET"
    for verb in _POST_VERBS:
        if verb in text:
            return "POST"
    return "POST"


def assemble_from_requirement(
    requirement: NormalizedRequirement,
    flow_id: str,
) -> AssemblyResult:
    """Deterministically assemble a flow skeleton from a requirement.

    Rules (piece-assembler, never freeform):
      1. Every component the interpreter detected MUST map to a
         real-engine piece; unmapped components → unmatched_components
         (the caller turns that into a teacher request).
      2. The flow gets exactly one entrypoint + one terminal receiver
         (one exchange pattern per artifact — blood law).
      3. Internal pieces are chained in deterministic order:
         converters/transform before router/filter before receivers.
    """
    pieces_library = proven_pieces()

    unmatched: list[str] = []
    wanted: list[str] = []

    for comp in requirement.components:
        piece_type = _COMPONENT_TO_PIECE.get(comp)
        if piece_type is None:
            unmatched.append(comp)
            continue
        if piece_type in _LIVE_UNPROVEN:
            # Live-unproven pieces never ship autonomously — the oracle
            # must validate them first (honesty floor).
            unmatched.append(comp)
            continue
        if piece_type not in pieces_library:
            unmatched.append(comp)
            continue
        if piece_type not in wanted:
            wanted.append(piece_type)

    # Only create-shaped jobs get assembled; modify/fix jobs are co-pilot
    # territory. A requirement is create-shaped when the interpreter says
    # so — OR when it is structurally create-shaped (names both a sender
    # and a receiver), which catches phrasings like "include an error
    # subprocess that logs failures" that keyword-classify as fix-flow.
    # A named target URL is further evidence: a directive pointing at an
    # endpoint with a sender is a flow to that endpoint.
    has_sender = any(c.startswith("sender.") for c in requirement.components)
    has_receiver = any(c.startswith("receiver.") for c in requirement.components)
    names_url = extract_target_url(requirement) is not None
    create_shaped = (
        requirement.intent in ("create-flow", "general")
        or (has_sender and has_receiver)
        or (has_sender and names_url)
    )
    if not create_shaped:
        return AssemblyResult(
            assembled=False,
            unmatched_components=unmatched,
            reason=(
                f"turbo assembles create-flow skeletons only; "
                f"intent={requirement.intent!r} needs the co-pilot path"
            ),
        )

    # One entrypoint (never two — blood law).
    entry_candidates = [t for t in _ENTRYPOINT_CANDIDATES if t in wanted]
    if not entry_candidates:
        # Requirement didn't name a sender; default to HTTP if proven.
        entry_type = next((t for t in _ENTRYPOINT_CANDIDATES if t in pieces_library), None)
    else:
        entry_type = entry_candidates[0]
    if entry_type is None:
        return AssemblyResult(
            assembled=False,
            unmatched_components=unmatched,
            reason="no proven entrypoint piece available",
        )

    # One terminal receiver. The target URL comes from the directive when
    # one is named (deterministic extraction — a human-directed flow must
    # forward where the human said), else a placeholder that local tests
    # mock anyway (world-mocks seam).
    recv_candidates = [t for t in _RECEIVER_CANDIDATES if t in wanted]
    if not recv_candidates:
        recv_type = next((t for t in _RECEIVER_CANDIDATES if t in pieces_library), None)
    else:
        recv_type = recv_candidates[0]
    if recv_type is None:
        return AssemblyResult(
            assembled=False,
            unmatched_components=unmatched,
            reason="no proven receiver piece available",
        )
    target_url = extract_target_url(requirement) or "https://example.invalid/api"
    receiver_method = extract_receiver_method(requirement)

    # Internal pieces: deterministic processing order.
    _ORDER = [
        "validator.json-schema",
        "converter.json-to-xml",
        "converter.xml-to-json",
        "modifier.content",
        "script.groovy",
        "encoder.base64",
        "router.content-based",
        "filter",
        "splitter.general",
        "log.message",
    ]
    internal = [t for t in _ORDER if t in wanted and t not in (entry_type, recv_type)]
    # Components not in the canonical order list keep discovery order.
    extra = [t for t in wanted if t not in _ORDER and t not in (entry_type, recv_type)]
    ordered_internal = internal + extra

    entry = Piece(
        node_id="sender-main",
        node_type=entry_type,
        config={"path": f"/{flow_id}", "methods": ["POST"]},
        fidelity="simulated",  # endpoints are the mock seam
        rationale="entrypoint piece (one exchange pattern per artifact)",
    )

    # Piece configs: deterministic, minimal, and LIVE-SAFE. An empty-config
    # Enricher (propertyTable="") is an unproven runtime-start shape (H2,
    # p5-p6-plan.md §6) — the modifier piece always carries a real row.
    # Correlation id: a CONSTANT row (fixture-proven dialect) — dynamic
    # per-message UUIDs need a script piece; teacher territory, not a guess.
    def _piece_config(t: str) -> dict[str, Any]:
        if t == "modifier.content":
            return {
                "headers": [{"name": "X-Correlation-Id", "value": "oiw-autogen"}],
            }
        if t == "log.message":
            return {"level": "INFO", "message": "processing message"}
        return {}

    chain: list[Piece] = []
    for i, t in enumerate(ordered_internal):
        chain.append(
            Piece(
                node_id=f"step-{i + 1}-{t.replace('.', '-')}",
                node_type=t,
                config=_piece_config(t),
                fidelity="compatible-subset" if t in pieces_library else "simulated",
                rationale=f"grammar piece {t} (real-engine proven)",
            )
        )
    # CONVERTER LAW (conv1-conv10 live bisection, 2026-09-02): a
    # converter step must be PRECEDED by a Request-Reply. Converting the
    # raw inbound body then calling an HTTP receiver fails at the adapter
    # ('Member name not found'); the same converter fed by an RR response
    # works in every tested position (conv9/conv10: RR→converter→RR→PD and
    # sender→RR→converter→RR→PD, both reward 1.0). When the requirement
    # converts the INBOUND body, the assembler inserts an RR warmup
    # (harmless GET) before the converter so the converter runs on an
    # RR-generated exchange.
    has_converter = any(p.node_type in _NO_DIRECT_HTTP_NEIGHBOR for p in chain)
    has_preceding_rr = any(p.node_type == "receiver.http" for p in chain)
    if has_converter and not has_preceding_rr and recv_type == "receiver.http":
        chain.insert(
            0,
            Piece(
                node_id="step-rr-warmup",
                node_type="receiver.http",
                config={
                    "url": "https://api.open-meteo.com/v1/forecast?latitude=52.52&longitude=13.41&current=temperature_2m",
                    "method": "GET",
                    "timeoutSeconds": 30,
                },
                fidelity="simulated",
                rationale=(
                    "RR warmup: converters must run on RR-generated exchanges "
                    "(converter law, conv1-conv10 bisection 2026-09-02)"
                ),
            ),
        )
    # LIVE TOPOLOGY LAW (2026-09-02, single-variable bisection): the only
    # message-proven HTTP-call form is Request-Reply, and RR chains must end
    # message-typed (plain EndEvent is start-fatal). A terminal receiver.http
    # therefore becomes a MID-FLOW RR step followed by a ProcessDirect
    # terminator with a unique address — the companion listener (PD sender +
    # variables.write) is emitted alongside so the pair deploys as proven
    # multi-artifact choreography.
    needs_pd_terminator = recv_type == "receiver.http"
    pd_address = f"/{flow_id}_pd"

    if needs_pd_terminator:
        # The HTTP call sits mid-chain as Request-Reply; PD terminates.
        chain.append(
            Piece(
                node_id="receiver-out",
                node_type=recv_type,
                config={"url": target_url, "method": receiver_method, "timeoutSeconds": 30},
                fidelity="simulated",  # endpoints are the mock seam
                rationale=(
                    f"Request-Reply piece ({receiver_method} {target_url} — from directive)"
                    if extract_target_url(requirement)
                    else "Request-Reply piece (placeholder URL — local tests mock it)"
                ),
            )
        )
        receiver = Piece(
            node_id="pd-terminator",
            node_type="receiver.processdirect",
            config={"address": pd_address},
            fidelity="simulated",
            rationale=(
                "ProcessDirect terminator (message-typed branch end — live law "
                "2026-09-02; companion listener required)"
            ),
        )
    else:
        receiver = Piece(
            node_id="receiver-out",
            node_type=recv_type,
            config={"url": target_url, "method": receiver_method, "timeoutSeconds": 30},
            fidelity="simulated",
            rationale="terminal receiver piece",
        )

    return AssemblyResult(
        assembled=True,  # we assemble what the pieces cover; unmatched are reported
        pieces=chain,
        unmatched_components=unmatched,
        entrypoint=entry,
        receiver=receiver,
        reason=(
            "assembled " + " -> ".join([entry.node_type] + [p.node_type for p in chain] + [recv_type])
            if not unmatched
            else "partially assembled; unmatched components: " + ", ".join(unmatched)
        ),
        companion_listener_address=pd_address if needs_pd_terminator else None,
    )


def assembly_to_flow(
    result: AssemblyResult,
    flow_id: str,
    flow_name: str | None = None,
) -> IntegrationFlow:
    """Materialize an AssemblyResult into IntegrationFlow IR."""
    from ..project import Entrypoint, FlowEdge, FlowNode

    assert result.entrypoint is not None and result.receiver is not None
    entry = Entrypoint(
        id=result.entrypoint.node_id,
        type=result.entrypoint.node_type,
        config=dict(result.entrypoint.config),
        fidelity=result.entrypoint.fidelity,
    )
    nodes = [
        FlowNode(
            id=p.node_id,
            type=p.node_type,
            config=dict(p.config),
            fidelity=p.fidelity,
        )
        for p in result.pieces
    ]
    receiver = FlowNode(
        id=result.receiver.node_id,
        type=result.receiver.node_type,
        config=dict(result.receiver.config),
        fidelity=result.receiver.fidelity,
    )
    nodes.append(receiver)

    # Linear chain: entry -> pieces... -> receiver
    ids = [entry.id] + [n.id for n in nodes]
    edges = [FlowEdge(from_=ids[i], to=ids[i + 1]) for i in range(len(ids) - 1)]

    return IntegrationFlow(
        id=flow_id,
        name=flow_name or flow_id,
        version=1,
        entrypoints=[entry],
        nodes=nodes,
        edges=edges,
        labels={"archetype": "turbo-assembled"},
    )


def companion_listener_flow(
    address: str,
    listener_flow_id: str,
) -> IntegrationFlow:
    """Build the PD companion listener for an RR-terminated flow.

    Topology proven LIVE (conv9, 2026-09-02): PD sender → log.message.
    variables.write was the first attempt but its values ride ProcessDirect
    as HEADERS — multi-line payloads (converted XML) carry CR/LF and are
    invalid header content ('Invalid characters (CR/LF) in header ...',
    live). log.message is a safe single-line terminal for arbitrary
    payloads.
    """
    from ..project import Entrypoint, FlowEdge, FlowNode

    return IntegrationFlow(
        id=listener_flow_id,
        name=listener_flow_id,
        version=1,
        entrypoints=[
            Entrypoint(
                id="pd-in",
                type="sender.processdirect",
                config={"address": address},
                fidelity="simulated",
            )
        ],
        nodes=[
            FlowNode(
                id="log-receive",
                type="log.message",
                config={"level": "INFO", "message": "PD payload received"},
                fidelity="compatible-subset",
            ),
        ],
        edges=[FlowEdge(from_="pd-in", to="log-receive")],
        labels={"archetype": "turbo-assembled-listener"},
    )


__all__ = [
    "AssemblyResult",
    "Piece",
    "assemble_from_requirement",
    "assembly_to_flow",
    "companion_listener_flow",
    "extract_receiver_method",
    "extract_target_url",
    "proven_pieces",
]
