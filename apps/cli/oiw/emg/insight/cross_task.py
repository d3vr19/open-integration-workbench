"""Cross-task insight generator (WP-06 Task C-004).

Spec ref: §15.13 (Cross-Task Transfer).

Generates cross-task insights from expert-to-expert matches. A
cross-task insight is a reusable pattern that applies across different
tasks — e.g., "all HTTPS-to-HTTP flows should validate JSON input
before transformation."

The insight includes:
  - applies_when: the conditions under which this pattern applies
  - workflow: the sequence of actions to follow
  - safety: constraints extracted from the common subgraph
  - confidence: from the expert match
  - support_count: how many tasks support this pattern (starts at 2)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from ..matching.expert_to_expert import ExpertMatchResult
from ..task_store import TaskMemoryNode


@dataclass
class CrossTaskInsight:
    """A reusable cross-task pattern.

    Attributes:
        id: unique insight ID
        applies_when: conditions (archetype, protocols, operations)
        workflow: sequence of actions to follow
        safety: safety constraints
        confidence: match confidence (0.0–1.0)
        support_count: how many tasks support this pattern
        provenance: source task IDs + match stage
    """

    id: str
    applies_when: dict[str, Any]
    workflow: list[dict[str, Any]]
    safety: list[str]
    confidence: float
    support_count: int = 2
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "appliesWhen": self.applies_when,
            "workflow": self.workflow,
            "safety": self.safety,
            "confidence": self.confidence,
            "supportCount": self.support_count,
            "provenance": self.provenance,
        }


class CrossTaskInsightGenerator:
    """Generate cross-task insights from expert-to-expert matches."""

    def generate(
        self,
        task_a: TaskMemoryNode,
        task_b: TaskMemoryNode,
        match: ExpertMatchResult,
    ) -> CrossTaskInsight | None:
        """Create a cross-task insight from a successful expert match.

        Returns None if the match was rejected (no common subgraph).
        """
        if match.common_subgraph is None or match.stage == "rejected":
            return None

        common = match.common_subgraph

        return CrossTaskInsight(
            id=f"xinsight-{uuid.uuid4().hex[:12]}",
            applies_when=self._infer_applies_when(task_a, task_b),
            workflow=self._workflow_from_subgraph(common),
            safety=self._safety_constraints(common),
            confidence=match.confidence,
            support_count=2,
            provenance={
                "taskA": task_a.task_id,
                "taskB": task_b.task_id,
                "matchStage": match.stage,
                "compilerVersion": "0.1.0",
            },
        )

    def _infer_applies_when(self, task_a: TaskMemoryNode, task_b: TaskMemoryNode) -> dict[str, Any]:
        """Determine the conditions under which this pattern applies."""
        req_a = task_a.normalized_requirement
        req_b = task_b.normalized_requirement

        # Use the common archetype/protocols
        archetype = req_a.get("archetype") or req_b.get("archetype")
        source = req_a.get("source_protocol") or req_b.get("source_protocol")
        target = req_a.get("target_protocol") or req_b.get("target_protocol")

        # Common operations
        ops_a = set(req_a.get("operations", []))
        ops_b = set(req_b.get("operations", []))
        common_ops = list(ops_a & ops_b) if ops_a and ops_b else list(ops_a | ops_b)

        return {
            "archetype": archetype,
            "sourceProtocol": source,
            "targetProtocol": target,
            "operations": common_ops,
        }

    def _workflow_from_subgraph(self, common: Any) -> list[dict[str, Any]]:
        """Convert common subgraph nodes to workflow steps."""
        workflow = []
        for node in common.nodes:
            action = node.action
            if action is None:
                continue
            workflow.append(
                {
                    "action": list(action.normalized) if hasattr(action, "normalized") else [],
                    "result": "applied",
                }
            )
        return workflow

    def _safety_constraints(self, common: Any) -> list[str]:
        """Extract safety constraints from the common subgraph."""
        constraints: list[str] = []
        for node in common.nodes:
            action = node.action
            if action is None:
                continue
            normalized = action.normalized if hasattr(action, "normalized") else ()
            if (
                len(normalized) >= 1
                and normalized[0] == "flow.patch"
                and len(normalized) >= 3
                and "receiver" in str(normalized[2])
            ):
                constraints.append("require-credential-ref")
            if (
                len(normalized) >= 1
                and normalized[0] == "resource.write"
                and len(normalized) >= 3
                and "schema" in str(normalized[2])
            ):
                constraints.append("validate-schema-content")
        return list(dict.fromkeys(constraints))  # dedupe


__all__ = ["CrossTaskInsight", "CrossTaskInsightGenerator"]
