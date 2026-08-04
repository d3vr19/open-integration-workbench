"""Cross-task edge store (WP-06 Task C-005).

Spec ref: §15.13 (Cross-Task Transfer).

Stores cross-task edges — directed connections between task memory
nodes that represent reusable patterns. When a pattern is reused
successfully, the edge's support_count is incremented, building
evidence that the pattern generalizes.

The edge store is the graph structure that enables "pattern popularity":
patterns with high support_count are preferred during retrieval.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .insight.cross_task import CrossTaskInsight


@dataclass
class CrossTaskEdge:
    """A directed edge between two task memory nodes.

    Attributes:
        id: unique edge ID
        source_task_id: the task that produced the insight
        target_task_id: the task that can benefit from the insight
        insight: the cross-task insight
        similarity_score: embedding similarity between the two tasks
        times_applied: how many times this pattern was successfully reused
        created_at: creation timestamp
    """

    id: str
    source_task_id: str
    target_task_id: str
    insight: CrossTaskInsight
    similarity_score: float
    times_applied: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sourceTaskId": self.source_task_id,
            "targetTaskId": self.target_task_id,
            "insight": self.insight.to_dict(),
            "similarityScore": self.similarity_score,
            "timesApplied": self.times_applied,
            "createdAt": self.created_at,
        }


class CrossTaskEdgeStore:
    """In-memory store for cross-task edges.

    For production, replace with a graph database (Neo4j, etc.).
    """

    def __init__(self) -> None:
        self._edges: dict[str, CrossTaskEdge] = {}
        self._by_source: dict[str, list[str]] = {}  # task_id → edge_ids
        self._by_target: dict[str, list[str]] = {}  # task_id → edge_ids

    def add_edge(
        self,
        source_task_id: str,
        target_task_id: str,
        insight: CrossTaskInsight,
        similarity_score: float = 0.0,
    ) -> str:
        """Add a cross-task edge. Returns edge ID."""
        edge_id = f"edge-{uuid.uuid4().hex[:12]}"
        edge = CrossTaskEdge(
            id=edge_id,
            source_task_id=source_task_id,
            target_task_id=target_task_id,
            insight=insight,
            similarity_score=similarity_score,
        )
        self._edges[edge_id] = edge
        self._by_source.setdefault(source_task_id, []).append(edge_id)
        self._by_target.setdefault(target_task_id, []).append(edge_id)
        return edge_id

    def get_edges_for_task(
        self,
        task_id: str,
        min_confidence: float = 0.5,
        max_edges: int = 5,
    ) -> list[CrossTaskEdge]:
        """Get cross-task edges for a task, sorted by confidence.

        Checks both source and target edges — a task can both produce
        insights (source) and benefit from them (target).

        Args:
            task_id: The task to get edges for.
            min_confidence: Minimum insight confidence threshold.
            max_edges: Maximum number of edges to return.

        Returns:
            List of CrossTaskEdge, sorted by insight confidence descending.
        """
        edge_ids = set(self._by_source.get(task_id, []) + self._by_target.get(task_id, []))
        edges = [
            self._edges[eid]
            for eid in edge_ids
            if eid in self._edges and self._edges[eid].insight.confidence >= min_confidence
        ]
        edges.sort(key=lambda e: e.insight.confidence, reverse=True)
        return edges[:max_edges]

    def increment_support_count(self, edge_id: str) -> None:
        """Increment the support count when a pattern is reused successfully."""
        edge = self._edges.get(edge_id)
        if edge:
            edge.times_applied += 1
            edge.insight.support_count += 1

    def get(self, edge_id: str) -> CrossTaskEdge | None:
        """Get an edge by ID."""
        return self._edges.get(edge_id)

    def count(self) -> int:
        """Total edge count."""
        return len(self._edges)

    def list_all(self) -> list[CrossTaskEdge]:
        """List all edges (for debugging/testing)."""
        return list(self._edges.values())


__all__ = ["CrossTaskEdge", "CrossTaskEdgeStore"]
