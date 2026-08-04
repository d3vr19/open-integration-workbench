"""Common subgraph extractor (WP-05 Task 11).

Spec ref: §15.9 (Common Subgraph).

Extracts the subgraph of actions that were already correct in the
exploration trajectory — i.e., nodes that appear in both the exploration
and the expert ADG, with matching result status (both "applied").

The common subgraph is the "successful part" of the exploration that
doesn't need correction. It's used by the insight compiler (Task 13)
as the `successful_workflow` field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..graph_builder import ActionDecisionGraph
from ..matching.common import MatchResult


@dataclass
class CommonNode:
    """A node that exists in both exploration and expert ADGs."""

    action: Any  # ActionRecord
    exploration_id: str
    expert_id: str


@dataclass
class CommonEdge:
    """An edge that exists in both ADGs with matching observation."""

    from_node: str
    to_node: str
    observation: tuple[str, ...]


@dataclass
class CommonSubgraph:
    """The subgraph of actions + edges already correct in the exploration."""

    nodes: list[CommonNode] = field(default_factory=list)
    edges: list[CommonEdge] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "action": n.action.normalized if n.action else None,
                    "explorationId": n.exploration_id,
                    "expertId": n.expert_id,
                }
                for n in self.nodes
            ],
            "edges": [
                {"from": e.from_node, "to": e.to_node, "observation": list(e.observation)} for e in self.edges
            ],
        }


class CommonSubgraphExtractor:
    """Extract the common subgraph (spec §15.9)."""

    def extract(
        self,
        exploration: ActionDecisionGraph,
        expert: ActionDecisionGraph,
        match: MatchResult,
    ) -> CommonSubgraph:
        """Return the subgraph of actions that were already correct.

        A node is "common" if:
          1. It appears in the correspondence (matched to an expert node)
          2. Both exploration and expert result_status are "applied"

        An edge is "common" if:
          1. Both endpoints are common nodes
          2. The expert ADG has an edge between the corresponding expert nodes
          3. The observation labels match
        """
        common_nodes: list[CommonNode] = []
        common_edges: list[CommonEdge] = []

        # Common nodes
        for exp_node, expert_node in match.correspondence.items():
            exp_data = exploration.graph.nodes[exp_node]
            expert_data = expert.graph.nodes[expert_node]
            if exp_data.get("result_status") == "applied" and expert_data.get("result_status") == "applied":
                common_nodes.append(
                    CommonNode(
                        action=exp_data.get("action"),
                        exploration_id=exp_node,
                        expert_id=expert_node,
                    )
                )

        # Common edges
        common_explored_ids = {n.exploration_id for n in common_nodes}
        for u, v, exp_edge_data in exploration.graph.edges(data=True):
            if u in common_explored_ids and v in common_explored_ids:
                expert_u = match.correspondence.get(u)
                expert_v = match.correspondence.get(v)
                if expert_u and expert_v and expert.graph.has_edge(expert_u, expert_v):
                    expert_edge_data = expert.graph.edges[expert_u, expert_v]
                    exp_obs = exp_edge_data.get("observation", ())
                    expert_obs = expert_edge_data.get("observation", ())
                    if tuple(exp_obs) == tuple(expert_obs):
                        common_edges.append(
                            CommonEdge(
                                from_node=u,
                                to_node=v,
                                observation=tuple(str(x) for x in exp_obs),
                            )
                        )

        return CommonSubgraph(nodes=common_nodes, edges=common_edges)


__all__ = ["CommonSubgraph", "CommonNode", "CommonEdge", "CommonSubgraphExtractor"]
