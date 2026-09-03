"""B2 — the tenant-law registry (evidence-attached, YAML, append-mostly).

Laws learned by the Experiment Engine land here. Consumers:

  - `oiw validate` (pre-deploy warnings): a flow violating a registry
    law gets a rule-code warning BEFORE any tenant round-trip.
  - the turbo assembler: placement laws (converter-must-be-preceded-by-RR
    class) drive piece placement instead of hardcoded comments.
  - future LLM prompts: laws are the distilled, evidence-backed ruleset
    the teacher model is quizzed against.

Format (tenant-laws.yaml):

    laws:
      - lawId: law-conv1
        statement: "a converter.json-to-xml step must be preceded by a Request-Reply"
        scope: converter.json-to-xml
        kind: insert
        origin: exp-abc123          # experiment id
        evidence:
          greenRungs: [...]         # rung ids (GREEN) — the law's support
          redRungs: [...]           # rung ids (RED) — the law's proof
        confidence: 1.0
        status: candidate           # candidate | ratified | retired
        recordedAt: 2026-09-02T...
        source: engine              # engine (B2-derived) | manual (blood law)

Manual blood laws (p5-p6-plan §6) are seeded with source=manual — they are
NOT to be relitigated; the engine may CORROBORATE them but never retire
them without operator action.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .engine import LawCandidate

STATUS_CANDIDATE = "candidate"
STATUS_RATIFIED = "ratified"
STATUS_RETIRED = "retired"


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass
class LawRecord:
    law_id: str
    statement: str
    scope: str
    kind: str
    origin: str  # experiment id | "manual"
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    status: str = STATUS_CANDIDATE
    recorded_at: str = field(default_factory=_now_iso)
    source: str = "engine"  # engine | manual

    def to_dict(self) -> dict[str, Any]:
        return {
            "lawId": self.law_id,
            "statement": self.statement,
            "scope": self.scope,
            "kind": self.kind,
            "origin": self.origin,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "status": self.status,
            "recordedAt": self.recorded_at,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LawRecord:
        return cls(
            law_id=d["lawId"],
            statement=d["statement"],
            scope=d.get("scope") or "flow.topology",
            kind=d.get("kind") or "unknown",
            origin=d.get("origin") or "unknown",
            evidence=d.get("evidence") or {},
            confidence=float(d.get("confidence") or 0.0),
            status=d.get("status") or STATUS_CANDIDATE,
            recorded_at=d.get("recordedAt") or "",
            source=d.get("source") or "engine",
        )


def candidate_to_record(
    candidate: LawCandidate,
    origin: str,
    *,
    status: str = STATUS_CANDIDATE,
) -> LawRecord:
    """Promote an engine-derived LawCandidate into a registry LawRecord."""
    return LawRecord(
        law_id=candidate.law_id,
        statement=candidate.statement,
        scope=candidate.scope,
        kind=candidate.kind,
        origin=origin,
        evidence={
            "greenRungs": candidate.green_rungs,
            "redRungs": candidate.red_rungs,
        },
        confidence=candidate.confidence,
        status=status,
        source="engine",
    )


class LawRegistry:
    """In-memory view over tenant-laws.yaml with atomic write-back."""

    def __init__(self, path: Path):
        self.path = path
        self.laws: list[LawRecord] = []

    # -- persistence ------------------------------------------------------

    def load(self) -> LawRegistry:
        if self.path.exists():
            data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            self.laws = [LawRecord.from_dict(d) for d in data.get("laws") or []]
        return self

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write (the emg-store pattern): temp + replace.
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            yaml.safe_dump({"laws": [law.to_dict() for law in self.laws]}, sort_keys=False),
            encoding="utf-8",
        )
        tmp.replace(self.path)
        return self.path

    # -- operations -------------------------------------------------------

    def add(self, record: LawRecord) -> LawRecord:
        if record.law_id in {law.law_id for law in self.laws}:
            record.law_id = f"{record.law_id}-{uuid.uuid4().hex[:4]}"
        self.laws.append(record)
        return record

    def add_many(self, records: list[LawRecord]) -> list[LawRecord]:
        return [self.add(r) for r in records]

    def get(self, law_id: str) -> LawRecord | None:
        return next((law for law in self.laws if law.law_id == law_id), None)

    def for_scope(self, scope: str) -> list[LawRecord]:
        return [law for law in self.laws if law.scope == scope]

    def ratified(self) -> list[LawRecord]:
        return [law for law in self.laws if law.status == STATUS_RATIFIED]

    def corroboration_for(self, candidate: LawCandidate) -> LawRecord | None:
        """An existing engine law this candidate repeats (same scope+kind).

        Corroborating evidence is MERGED into the existing law (appending
        rungs) rather than duplicating it — a law re-derived on a fresh
        campaign gets stronger, not duplicated.
        """
        for law in self.laws:
            if law.source != "engine":
                continue
            if law.scope == candidate.scope and law.kind == candidate.kind:
                return law
        return None

    def merge_evidence(self, law: LawRecord, candidate: LawCandidate) -> LawRecord:
        ev = law.evidence or {}
        green = list(ev.get("greenRungs") or [])
        red = list(ev.get("redRungs") or [])
        green.extend(r for r in candidate.green_rungs if r not in green)
        red.extend(r for r in candidate.red_rungs if r not in red)
        law.evidence = {"greenRungs": green, "redRungs": red}
        # confidence approaches 1.0 with independent red-rung proofs
        law.confidence = min(1.0, law.confidence + 0.25 * max(0, len(red) - 1))
        return law

    def record_candidates(
        self,
        candidates: list[LawCandidate],
        origin: str,
    ) -> list[LawRecord]:
        """Record law candidates — merge corroborations, add new laws.

        Manual blood laws are never touched (source=manual is out of
        scope for corroboration-for-merge; they were derived by human
        bisection and are already ratified).
        """
        out: list[LawRecord] = []
        for c in candidates:
            existing = self.corroboration_for(c)
            if existing is not None:
                self.merge_evidence(existing, c)
                out.append(existing)
            else:
                out.append(self.add(candidate_to_record(c, origin)))
        return out


def load_registry(path: Path | None = None) -> LawRegistry:
    """Resolve the registry path like the EMG store: OIW_WORKSPACE/PWD."""
    if path is not None:
        return LawRegistry(path).load()
    import os

    ws = os.environ.get("OIW_WORKSPACE") or str(Path.cwd())
    return LawRegistry(Path(ws) / ".oiw" / "tenant-laws.yaml").load()


__all__ = [
    "LawRecord",
    "LawRegistry",
    "STATUS_CANDIDATE",
    "STATUS_RATIFIED",
    "STATUS_RETIRED",
    "candidate_to_record",
    "load_registry",
]
