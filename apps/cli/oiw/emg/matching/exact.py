"""Exact matcher — Stage 1 (WP-05 Task 9).

Spec ref: §15.7 (Matching Stages), Stage 1: exact match.

Matches nodes by stable tuple equality: the normalized action tuple
(tool, op, componentType, semanticTarget, paramClass) must be identical
on both sides. IR version and plugin version must also match.

This is the strictest matching stage — it produces high-confidence
correspondences but misses semantically equivalent actions that use
different naming (handled by RuleBasedMatcher in Stage 2).
"""

from __future__ import annotations

from ..graph_builder import ActionDecisionGraph
from .common import MatchResult


class ExactMatcher:
    """Stage 1: stable tuple equality, same IR/plugin version."""

    # The virtual INIT node ID — skipped in matching (it's a synthetic start node).
    INIT_NODE_ID = "INIT"

    def match(
        self,
        exploration: ActionDecisionGraph,
        expert: ActionDecisionGraph,
    ) -> MatchResult:
        """Find exact node correspondences between exploration and expert.

        Args:
            exploration: the ADG built from the (possibly failed) exploration trajectory.
            expert: the ADG built from the approved expert trajectory.

        Returns:
            MatchResult with correspondence dict + confidence + unmatched sets.
        """
        correspondence: dict[str, str] = {}

        for exp_node in exploration.graph.nodes:
            if exp_node == self.INIT_NODE_ID:
                continue  # Skip INIT — it's a virtual node
            exp_data = exploration.graph.nodes[exp_node]
            for expert_node in expert.graph.nodes:
                if expert_node == self.INIT_NODE_ID:
                    continue
                expert_data = expert.graph.nodes[expert_node]
                if self._nodes_match(exp_data, expert_data):
                    correspondence[exp_node] = expert_node
                    break

        all_explored = {n for n in exploration.graph.nodes if n != self.INIT_NODE_ID}
        all_expert = {n for n in expert.graph.nodes if n != self.INIT_NODE_ID}

        confidence = len(correspondence) / max(len(all_explored), 1) if all_explored else 0.0

        return MatchResult(
            stage="exact",
            correspondence=correspondence,
            confidence=confidence,
            unmatched_explored=all_explored - set(correspondence.keys()),
            unmatched_expert=all_expert - set(correspondence.values()),
        )

    def _nodes_match(self, a: dict, b: dict) -> bool:
        """Check if two nodes have identical normalized actions + versions.

        The action dataclass is stored on the node; we compare its
        normalized tuple. IR/plugin version comparison is included
        but defaults to matching when not set (backward compat).
        """
        a_action = a.get("action")
        b_action = b.get("action")
        if a_action is None or b_action is None:
            return False

        # Compare normalized tuples
        a_norm = tuple(str(x) for x in a_action.normalized)
        b_norm = tuple(str(x) for x in b_action.normalized)
        if a_norm != b_norm:
            return False

        # Compare IR/plugin versions if present
        a_ir = a.get("ir_version")
        b_ir = b.get("ir_version")
        if a_ir is not None and b_ir is not None and a_ir != b_ir:
            return False

        a_plugin = a.get("plugin_version")
        b_plugin = b.get("plugin_version")
        return not (a_plugin is not None and b_plugin is not None and a_plugin != b_plugin)


__all__ = ["ExactMatcher"]
