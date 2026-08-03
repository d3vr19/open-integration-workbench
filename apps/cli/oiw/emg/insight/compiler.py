"""EMG insight compilation (WP-05 Task 13).

Spec ref: §15.9 (Insight Compilation).

Compiles the common subgraph + edit path into a machine-readable
IntraTaskInsight that the agent can use for future corrections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..graph_builder import ActionDecisionGraph
from ..subgraph.common import CommonSubgraph
from ..subgraph.edit_path import EditOperation, GraphEditPath


@dataclass
class CorrectionRule:
    """A single correction rule: trigger → avoid/prefer.

    Attributes:
        trigger: what observation/action state triggers this correction
        avoid: actions to avoid (for DELETE/RELABEL)
        prefer: actions to prefer (for INSERT)
        confidence: 0.0–1.0
    """

    trigger: dict[str, Any]
    avoid: list[dict[str, Any]] = field(default_factory=list)
    prefer: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class InsightProvenance:
    """Provenance for an insight — links back to source trajectories."""

    exploration_trajectory_id: str
    expert_trajectory_id: str
    match_stage: str  # exact | rule-based | alignment
    compiler_version: str = "0.1.0"


@dataclass
class IntraTaskInsight:
    """Machine-readable correction memory for a specific task.

    Attributes:
        task_id: the task this insight applies to
        successful_workflow: the common subgraph (what was already correct)
        corrections: list of CorrectionRule (what to fix)
        provenance: links to source trajectories
    """

    task_id: str
    successful_workflow: list[dict[str, Any]] = field(default_factory=list)
    corrections: list[CorrectionRule] = field(default_factory=list)
    provenance: InsightProvenance | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "successfulWorkflow": self.successful_workflow,
            "corrections": [
                {
                    "trigger": c.trigger,
                    "avoid": c.avoid,
                    "prefer": c.prefer,
                    "confidence": c.confidence,
                }
                for c in self.corrections
            ],
            "provenance": {
                "explorationTrajectoryId": self.provenance.exploration_trajectory_id,
                "expertTrajectoryId": self.provenance.expert_trajectory_id,
                "matchStage": self.provenance.match_stage,
                "compilerVersion": self.provenance.compiler_version,
            }
            if self.provenance
            else None,
        }


class IntraTaskInsightCompiler:
    """Compile common subgraph + edit path into machine-readable insight."""

    def compile(
        self,
        task_id: str,
        exploration: ActionDecisionGraph,
        expert: ActionDecisionGraph,
        common: CommonSubgraph,
        edit_path: GraphEditPath,
        match_stage: str = "rule-based",
    ) -> IntraTaskInsight:
        """Compile an insight from the matching results.

        Args:
            task_id: the task this insight applies to.
            exploration: the exploration ADG.
            expert: the expert ADG.
            common: the common subgraph (successful part).
            edit_path: the edit path (corrections needed).
            match_stage: which matcher stage produced the correspondence.

        Returns:
            IntraTaskInsight with successful_workflow + corrections.
        """
        return IntraTaskInsight(
            task_id=task_id,
            successful_workflow=self._serialize_subgraph(common),
            corrections=[self._compile_correction(op) for op in edit_path.operations],
            provenance=InsightProvenance(
                exploration_trajectory_id=exploration.trajectory_id,
                expert_trajectory_id=expert.trajectory_id,
                match_stage=match_stage,
            ),
        )

    def _serialize_subgraph(self, common: CommonSubgraph) -> list[dict[str, Any]]:
        """Machine-readable workflow: sequence of actions with results."""
        return [
            {
                "action": tuple(n.action.normalized) if n.action else None,
                "result": "applied",
            }
            for n in common.nodes
        ]

    def _compile_correction(self, op: EditOperation) -> CorrectionRule:
        """Convert an edit operation into a correction rule."""
        if op.type == "DELETE":
            return CorrectionRule(
                trigger={
                    "diagnostic": "FAILED",
                    "action": tuple(op.action.normalized) if op.action else None,
                },
                avoid=[{"action": tuple(op.action.normalized) if op.action else None}],
                prefer=[],
                confidence=1.0,
            )
        if op.type == "INSERT":
            return CorrectionRule(
                trigger={"precedes": tuple(op.action.normalized) if op.action else None},
                avoid=[],
                prefer=[{"action": tuple(op.action.normalized) if op.action else None}],
                confidence=1.0,
            )
        if op.type == "RELABEL":
            return CorrectionRule(
                trigger={
                    "action": tuple(op.action.normalized) if op.action else None,
                    "fromStatus": op.from_status,
                },
                avoid=[{"status": op.from_status}],
                prefer=[{"status": op.to_status}],
                confidence=1.0,
            )
        # EDGE_CORRECTION
        return CorrectionRule(
            trigger={"action": tuple(op.action.normalized) if op.action else None},
            avoid=[{"successors": sorted(op.from_successors)}],
            prefer=[{"successors": sorted(op.to_successors)}],
            confidence=0.9,
        )


__all__ = [
    "IntraTaskInsight",
    "CorrectionRule",
    "InsightProvenance",
    "IntraTaskInsightCompiler",
]
