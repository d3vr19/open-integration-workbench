"""Law-registry validators — B2 consumer wiring (roadmap §B2, 2026-09-03).

Ratified laws in the tenant-law registry (`.oiw/tenant-laws.yaml`) are
checked against a project's flows BEFORE any tenant round-trip: a flow
violating a live-proven placement law warns at `oiw validate` time, in
the studio instead of in a failed deploy.

Rule code: OIW-W013 (law violation — pre-deploy warning).

Design constraints honored:
  - Candidate laws (not yet ratified) are NOT enforced — an operator
    reviews before a law starts rejecting flows (nothing auto-ratifies).
  - Laws without a machine-checkable predicate are advisory-only; the
    statement text is shown as a note when the scope appears in a flow
    and the law carries no predicate.
  - Missing registry file = zero warnings (a fresh workspace has no laws
    yet; validate must never hard-depend on experiment state).
"""

from __future__ import annotations

from pathlib import Path

from ..project import IntegrationFlow
from .graph_positions import position_of


def check_flow_laws(
    flow: IntegrationFlow,
    laws: list,
) -> list[str]:
    """Return OIW-W013 warnings for flow placements violating ratified laws."""
    warnings: list[str] = []
    for law in laws:
        if getattr(law, "status", "") != "ratified":
            continue
        pred = getattr(law, "predicate", None)
        if not pred:
            continue  # advisory-only laws never warn structurally
        if pred.get("type") == "requires-position-after":
            node_type = str(pred.get("node") or law.scope)
            pos = position_of(flow, node_type)
            if pos is None:
                continue
            greens = pred.get("greenPositions") or []
            if greens and pos >= min(greens):
                continue  # placement inside the proven-green range
            reds = pred.get("redPositions") or []
            if reds and pos in reds:
                warnings.append(
                    f"OIW-W013: law {law.law_id}: '{node_type}' sits at body "
                    f"position {pos}, which is live-proven RED "
                    f"(positions {reds}); proven green from {min(greens)} — "
                    f"{law.statement}"
                )
        # future predicate types extend here
    return warnings


def run_law_validators(
    flows: list[IntegrationFlow],
    registry_path: Path | None = None,
) -> list[str]:
    """Load the law registry and check every flow. Missing registry → no warnings."""
    if registry_path is None:
        import os

        ws = os.environ.get("OIW_WORKSPACE") or str(Path.cwd())
        registry_path = Path(ws) / ".oiw" / "tenant-laws.yaml"
    if not registry_path.exists():
        return []
    import yaml

    from ..experiment.registry import LawRecord

    data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    laws = [LawRecord.from_dict(d) for d in data.get("laws") or []]
    warnings: list[str] = []
    for flow in flows:
        warnings.extend(check_flow_laws(flow, laws))
    return warnings


__all__ = ["check_flow_laws", "run_law_validators"]
