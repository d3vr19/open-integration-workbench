"""Shared types for EMG matching (WP-05 Tasks 9-10).

Spec ref: §15.7 (Matching Stages).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MatchResult:
    """Result of a graph matching stage.

    Attributes:
        stage: "exact" | "rule-based" | "alignment"
        correspondence: mapping from exploration node ID → expert node ID
        confidence: fraction of exploration nodes matched (0.0–1.0)
        unmatched_explored: exploration nodes with no expert match
        unmatched_expert: expert nodes with no exploration match
    """

    stage: str
    correspondence: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    unmatched_explored: set[str] = field(default_factory=set)
    unmatched_expert: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "correspondence": dict(self.correspondence),
            "confidence": self.confidence,
            "unmatchedExplored": sorted(self.unmatched_explored),
            "unmatchedExpert": sorted(self.unmatched_expert),
        }


__all__ = ["MatchResult"]
