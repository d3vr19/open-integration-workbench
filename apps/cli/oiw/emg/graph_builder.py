"""Action Decision Graph (ADG) builder (WP-05 Task 8).

Spec ref: §15.3 (ADG Structure), §15.6 (Node Reuse).

Converts an EngineeringTrajectory into a directed, edge-labelled graph
using networkx. The ADG is the substrate for graph matching (Tasks 9-10)
and edit-path extraction (Tasks 11-12).

Structure:
  - Virtual INIT node (represents the start state)
  - One node per unique action (identified by normalized tuple)
  - Edge from prev_node → action_node, labelled with the observation
    that preceded the action
  - Node reuse: if the same normalized action appears twice, the node
    is reused (both edges point to it)
  - Uninformative observations (repeated failures, no-ops) don't
    advance prev_node (spec §15.5)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import networkx as nx

from ..agent.normalization import normalize_observation
from ..agent.trajectory import EngineeringTrajectory, ObservationRecord


@dataclass
class ActionDecisionGraph:
    """A directed, edge-labelled graph built from a trajectory.

    Attributes:
        graph: networkx.DiGraph with node/edge attributes
        trajectory_id: the source trajectory's ID
    """

    graph: nx.DiGraph
    trajectory_id: str

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence/debugging."""
        return {
            "trajectoryId": self.trajectory_id,
            "nodes": [{"id": n, **self.graph.nodes[n]} for n in self.graph.nodes],
            "edges": [{"source": u, "target": v, **self.graph.edges[u, v]} for u, v in self.graph.edges],
        }


class ActionDecisionGraphBuilder:
    """Builds an ADG from an EngineeringTrajectory (spec §15.3)."""

    INIT_NODE_ID = "INIT"

    def build(self, trajectory: EngineeringTrajectory) -> ActionDecisionGraph:
        """Convert a trajectory into an Action Decision Graph.

        Args:
            trajectory: The recorded trajectory (from TrajectoryRecorder).

        Returns:
            ActionDecisionGraph with nodes for each unique action and
            edges labelled with observations.
        """
        G = nx.DiGraph()
        G.graph["trajectory_id"] = trajectory.metadata.id
        G.graph["query"] = trajectory.spec.query.normalized
        G.graph["reward"] = trajectory.spec.outcome.reward
        G.graph["status"] = trajectory.spec.outcome.status

        # Virtual INIT node
        G.add_node(
            self.INIT_NODE_ID,
            action=None,
            observation=None,
            node_type="init",
        )

        prev_node = self.INIT_NODE_ID
        for step in trajectory.spec.steps:
            if step.action is None:
                continue

            action_id = self._action_node_id(step.action)

            # Node reuse: if action already exists, reuse it (spec §15.6)
            if action_id not in G:
                G.add_node(
                    action_id,
                    action=step.action,
                    result_status=step.result.status if step.result else "unknown",
                    provenance=step.action.argumentsDigest,
                    node_type="action",
                )

            # Edge: observation that preceded this action
            obs_label = (
                normalize_observation(step.observation.__dict__)
                if step.observation
                else ("unknown", "NONE", "", "")
            )
            G.add_edge(
                prev_node,
                action_id,
                observation=obs_label,
                diagnostic_code=step.observation.diagnosticCode if step.observation else None,
                step_index=step.index,
            )

            # Only advance prev_node if the observation was informative
            if self._is_informative(step.observation):
                prev_node = action_id

        return ActionDecisionGraph(graph=G, trajectory_id=trajectory.metadata.id)

    def _action_node_id(self, action: Any) -> str:
        """Stable node ID from the normalized action tuple.

        The normalized tuple is (tool, op, componentType, semanticTarget, paramClass).
        We join with ':' to form a stable string ID.
        """
        normalized = tuple(str(x) for x in action.normalized)
        return ":".join(normalized)

    def _is_informative(self, observation: ObservationRecord | None) -> bool:
        """Check if an observation is informative (spec §15.5).

        Uninformative observations (repeated failures, no-ops) don't
        advance the prev_node pointer. This prevents the ADG from
        having long chains of identical failure edges.
        """
        if observation is None:
            return False
        return observation.type not in ("repeated-failure", "no-op")


__all__ = ["ActionDecisionGraph", "ActionDecisionGraphBuilder"]
