"""Task memory node store for cross-task retrieval (WP-06 Task C-002).

Spec ref: §15.13 (Cross-Task Transfer).

Stores task memory nodes — one per completed task — with their requirement
embeddings. Enables the EMG to find similar tasks across different flows
and projects, not just within a single task.

This is the substrate for EMG Phase C: when a new requirement arrives,
the task store finds the K most similar approved tasks and their insights
become candidates for cross-task transfer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from ..agent.interpreter import NormalizedRequirement
from .embedding import RequirementEmbedder


@dataclass
class TaskMemoryNode:
    """A task memory node — one per completed task with an approved insight.

    Attributes:
        id: unique node ID
        task_id: the original task ID
        requirement_embedding: TF-IDF vector for similarity search
        normalized_requirement: the structured requirement
        insight_ref: reference to the IntraTaskInsight (if any)
        reward: the reward vector from execution
        approval: PROJECT_APPROVED | ORGANIZATION_APPROVED | DEPRECATED
        target_profiles: which SAP CI profiles this applies to
        confidentiality_scope: project | organization
    """

    id: str
    task_id: str
    requirement_embedding: list[float]
    normalized_requirement: dict[str, Any]
    insight_ref: str | None = None
    reward: dict[str, Any] = field(default_factory=dict)
    approval: str = "CAPTURED"
    target_profiles: list[str] = field(default_factory=lambda: ["sap-cloud-integration-2026-07"])
    confidentiality_scope: str = "project"
    project_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "taskId": self.task_id,
            "requirementEmbedding": self.requirement_embedding,
            "normalizedRequirement": self.normalized_requirement,
            "insightRef": self.insight_ref,
            "reward": self.reward,
            "approval": self.approval,
            "targetProfiles": self.target_profiles,
            "confidentialityScope": self.confidentiality_scope,
            "projectId": self.project_id,
        }


class TaskMemoryNodeStore:
    """In-memory store for task memory nodes.

    For production, replace with a pgvector-backed database. The
    interface stays the same.
    """

    def __init__(self, embedder: RequirementEmbedder | None = None):
        self._nodes: dict[str, TaskMemoryNode] = {}
        self._embedder = embedder or RequirementEmbedder()

    def insert(self, node: TaskMemoryNode) -> str:
        """Insert a task memory node. Returns node ID."""
        self._nodes[node.id] = node
        return node.id

    def insert_from_requirement(
        self,
        requirement: NormalizedRequirement,
        task_id: str,
        project_id: str | None = None,
        insight_ref: str | None = None,
        reward: dict[str, Any] | None = None,
    ) -> TaskMemoryNode:
        """Create + insert a node from a normalized requirement.

        Convenience method: embeds the requirement and creates the node.
        """
        embedding = self._embedder.embed(requirement)
        node = TaskMemoryNode(
            id=f"task-mem-{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            requirement_embedding=embedding.vector,
            normalized_requirement=requirement.to_dict(),
            insight_ref=insight_ref,
            reward=reward or {},
            approval="PROJECT_APPROVED",
            project_id=project_id,
        )
        self._nodes[node.id] = node
        return node

    def get(self, node_id: str) -> TaskMemoryNode | None:
        """Get a task memory node by ID."""
        return self._nodes.get(node_id)

    def search_similar(
        self,
        embedding: list[float],
        top_k: int = 5,
        min_similarity: float = 0.3,
        project_id: str | None = None,
    ) -> list[tuple[TaskMemoryNode, float]]:
        """Find top-K similar task memory nodes by embedding similarity.

        Args:
            embedding: The query embedding vector.
            top_k: Maximum number of results.
            min_similarity: Minimum cosine similarity threshold.
            project_id: Optional project filter.

        Returns:
            List of (node, similarity) tuples, sorted by similarity descending.
        """
        results: list[tuple[TaskMemoryNode, float]] = []

        for node in self._nodes.values():
            if node.approval not in ("PROJECT_APPROVED", "ORGANIZATION_APPROVED"):
                continue
            if project_id is not None and node.project_id != project_id:
                continue
            if node.confidentiality_scope == "project" and project_id != node.project_id:
                continue

            sim = _cosine_similarity(embedding, node.requirement_embedding)
            if sim >= min_similarity:
                results.append((node, sim))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def search_similar_requirement(
        self,
        requirement: NormalizedRequirement,
        top_k: int = 5,
        min_similarity: float = 0.3,
        project_id: str | None = None,
    ) -> list[tuple[TaskMemoryNode, float]]:
        """Find similar tasks by embedding a requirement and searching."""
        embedding = self._embedder.embed(requirement)
        return self.search_similar(
            embedding.vector,
            top_k=top_k,
            min_similarity=min_similarity,
            project_id=project_id,
        )

    def list_approved(
        self,
        project_id: str | None = None,
    ) -> list[TaskMemoryNode]:
        """List all approved task memory nodes."""
        results = []
        for node in self._nodes.values():
            if node.approval not in ("PROJECT_APPROVED", "ORGANIZATION_APPROVED"):
                continue
            if project_id is not None and node.project_id != project_id:
                continue
            results.append(node)
        return results

    def count(self) -> int:
        """Total node count."""
        return len(self._nodes)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# Need math import
import math  # noqa: E402

__all__ = ["TaskMemoryNode", "TaskMemoryNodeStore"]
