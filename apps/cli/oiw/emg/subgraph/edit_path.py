"""Graph edit path extractor (WP-05 Task 12).

Spec ref: §15.9 (Edit Path).

Extracts the operations needed to transform the exploration ADG into
the expert ADG:
  - DELETE: exploration nodes not in the correspondence (wrong/extra actions)
  - INSERT: expert nodes not in the correspondence (missing actions)
  - RELABEL: corresponding nodes with different result_status
  - EDGE_CORRECTION: corresponding nodes with different successors

These operations become the `corrections` list in the compiled insight
(Task 13), which the agent can use to avoid repeating failed approaches
and prefer the expert's successful ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..graph_builder import ActionDecisionGraph
from ..matching.common import MatchResult
from .common import CommonSubgraph


@dataclass
class EditOperation:
    """A single graph edit operation.

    Attributes:
        type: DELETE | INSERT | RELABEL | EDGE_CORRECTION
        target: the node ID being operated on
        action: the ActionRecord (for DELETE/INSERT/RELABEL)
        reason: human-readable explanation
        from_status / to_status: for RELABEL
        from_successors / to_successors: for EDGE_CORRECTION
    """

    type: str
    target: str
    action: Any = None
    reason: str = ""
    from_status: str | None = None
    to_status: str | None = None
    from_successors: set[str] = field(default_factory=set)
    to_successors: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "target": self.target,
            "action": self.action.normalized if self.action else None,
            "reason": self.reason,
            "fromStatus": self.from_status,
            "toStatus": self.to_status,
            "fromSuccessors": sorted(self.from_successors),
            "toSuccessors": sorted(self.to_successors),
        }


@dataclass
class GraphEditPath:
    """The full set of edit operations."""

    operations: list[EditOperation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"operations": [op.to_dict() for op in self.operations]}


class GraphEditPathExtractor:
    """Extract INSERT/DELETE/RELABEL/EDGE_CORRECTION operations (spec §15.9)."""

    def extract(
        self,
        exploration: ActionDecisionGraph,
        expert: ActionDecisionGraph,
        match: MatchResult,
        common: CommonSubgraph,
    ) -> GraphEditPath:
        """Return operations needed to transform exploration into expert.

        Args:
            exploration: the exploration ADG.
            expert: the expert ADG.
            match: the MatchResult from exact + rule-based matching.
            common: the CommonSubgraph from the common subgraph extractor.

        Returns:
            GraphEditPath with all operations.
        """
        operations: list[EditOperation] = []

        # DELETE: exploration nodes not in correspondence
        for exp_node in match.unmatched_explored:
            exp_data = exploration.graph.nodes[exp_node]
            operations.append(
                EditOperation(
                    type="DELETE",
                    target=exp_node,
                    action=exp_data.get("action"),
                    reason="Not present in expert trajectory",
                )
            )

        # INSERT: expert nodes not in correspondence
        for expert_node in match.unmatched_expert:
            expert_data = expert.graph.nodes[expert_node]
            operations.append(
                EditOperation(
                    type="INSERT",
                    target=expert_node,
                    action=expert_data.get("action"),
                    reason="Required by expert trajectory",
                )
            )

        # RELABEL: corresponding nodes with different result_status
        for exp_node, expert_node in match.correspondence.items():
            exp_status = exploration.graph.nodes[exp_node].get("result_status")
            expert_status = expert.graph.nodes[expert_node].get("result_status")
            if exp_status != expert_status:
                operations.append(
                    EditOperation(
                        type="RELABEL",
                        target=exp_node,
                        action=exploration.graph.nodes[exp_node].get("action"),
                        reason=f"Outcome differs: {exp_status} → {expert_status}",
                        from_status=exp_status,
                        to_status=expert_status,
                    )
                )

        # EDGE_CORRECTION: corresponding nodes with different successors
        for exp_node, expert_node in match.correspondence.items():
            exp_successors = set(exploration.graph.successors(exp_node))
            expert_successors = set(expert.graph.successors(expert_node))
            # Map expert successors back to exploration IDs for comparison
            exp_successor_ids = exp_successors
            expert_successor_mapped = {k for k, v in match.correspondence.items() if v in expert_successors}
            if exp_successor_ids != expert_successor_mapped:
                operations.append(
                    EditOperation(
                        type="EDGE_CORRECTION",
                        target=exp_node,
                        action=exploration.graph.nodes[exp_node].get("action"),
                        reason="Different next actions after this node",
                        from_successors=exp_successor_ids,
                        to_successors=expert_successor_mapped,
                    )
                )

        return GraphEditPath(operations=operations)


__all__ = ["EditOperation", "GraphEditPath", "GraphEditPathExtractor"]
