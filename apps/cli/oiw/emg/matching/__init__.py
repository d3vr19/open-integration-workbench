"""EMG matching package (WP-05 Tasks 9-12).

Spec ref: §15.7 (Matching Stages).

Two-stage matching:
  1. ExactMatcher — stable tuple equality, same IR/plugin version
  2. RuleBasedMatcher — aliases, diagnostic class grouping, role mapping

Both produce a MatchResult with:
  - correspondence: {exploration_node_id: expert_node_id}
  - confidence: fraction of exploration nodes matched
  - unmatched_explored / unmatched_expert: sets for the next stage
"""

from __future__ import annotations

from .common import MatchResult
from .exact import ExactMatcher
from .rule_based import RuleBasedMatcher

__all__ = ["MatchResult", "ExactMatcher", "RuleBasedMatcher"]
