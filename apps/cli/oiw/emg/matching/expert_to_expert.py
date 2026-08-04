"""Expert-to-expert graph matching (WP-06 Task C-003).

Spec ref: §15.13 (Cross-Task Transfer).

Matches two expert ADGs to find common workflow patterns. Uses the
existing ExactMatcher + RuleBasedMatcher (Phase B) in a cascading
pipeline, then extracts the common subgraph.

This is the "graph matching" step of cross-task transfer: when two
expert trajectories share a common subgraph, that subgraph becomes a
reusable cross-task pattern.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..graph_builder import ActionDecisionGraph
from ..matching.exact import ExactMatcher
from ..matching.rule_based import RuleBasedMatcher
from ..subgraph.common import CommonSubgraph, CommonSubgraphExtractor


@dataclass
class ExpertMatchResult:
    """Result of matching two expert ADGs.

    Attributes:
        common_subgraph: the shared workflow (None if rejected)
        confidence: match confidence (0.0–1.0)
        stage: "exact" | "rule-based" | "rejected"
        reason: why this result was chosen
    """

    common_subgraph: CommonSubgraph | None
    confidence: float
    stage: str  # exact | rule-based | rejected
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "commonSubgraph": self.common_subgraph.to_dict() if self.common_subgraph else None,
            "confidence": self.confidence,
            "stage": self.stage,
            "reason": self.reason,
        }


class ExpertToExpertMatcher:
    """Match two expert decision graphs to find common subgraphs.

    Cascading pipeline:
      1. Exact matching (strict tuple equality)
      2. Rule-based matching (aliases, diagnostic classes, roles)
      3. Reject if confidence below threshold
    """

    EXACT_THRESHOLD = 0.8
    RULE_THRESHOLD = 0.5

    def match(
        self,
        expert_a: ActionDecisionGraph,
        expert_b: ActionDecisionGraph,
    ) -> ExpertMatchResult:
        """Find common workflow between two expert trajectories.

        Args:
            expert_a: First expert ADG.
            expert_b: Second expert ADG.

        Returns:
            ExpertMatchResult with common subgraph + confidence + stage.
        """
        # Stage 1: Exact matching
        exact = ExactMatcher().match(expert_a, expert_b)
        if exact.confidence >= self.EXACT_THRESHOLD:
            common = CommonSubgraphExtractor().extract(expert_a, expert_b, exact)
            return ExpertMatchResult(
                common_subgraph=common,
                confidence=exact.confidence,
                stage="exact",
                reason=f"exact match confidence {exact.confidence:.2f} >= {self.EXACT_THRESHOLD}",
            )

        # Stage 2: Rule-based matching
        rule = RuleBasedMatcher().match(expert_a, expert_b, exact)
        if rule.confidence >= self.RULE_THRESHOLD:
            common = CommonSubgraphExtractor().extract(expert_a, expert_b, rule)
            return ExpertMatchResult(
                common_subgraph=common,
                confidence=rule.confidence,
                stage="rule-based",
                reason=f"rule-based match confidence {rule.confidence:.2f} >= {self.RULE_THRESHOLD}",
            )

        # Stage 3: Reject low-confidence matches
        return ExpertMatchResult(
            common_subgraph=None,
            confidence=rule.confidence,
            stage="rejected",
            reason=f"confidence {rule.confidence:.2f} below threshold {self.RULE_THRESHOLD}",
        )


__all__ = ["ExpertMatchResult", "ExpertToExpertMatcher"]
