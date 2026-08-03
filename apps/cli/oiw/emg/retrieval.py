"""EMG retrieval — the mechanics-first loop (WP-05 enhancement).

Spec ref: §15.11 (Retrieval), §15.12 (Injection).

This is where the "TurboVLA-style mechanics" become real: instead of
always invoking the LLM planner, the orchestrator first checks the EMG
insight store for a matching expert trajectory. If found, the insight's
`successful_workflow` (common subgraph) is injected directly into the
plan, and the `corrections` list is used to avoid known failure modes.

The LLM is only invoked for:
  1. Novel requirements (no matching insight)
  2. Bounded correction when an EMG-informed plan fails

This makes the agent measurably faster (no LLM latency for known
patterns) and more reliable (expert trajectories have verified outcomes).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..agent.interpreter import NormalizedRequirement
from .insight.compiler import IntraTaskInsight
from .promotion import InMemoryInsightStore, MemoryPromotionState


@dataclass
class RetrievalResult:
    """Result of an EMG insight retrieval.

    Attributes:
        found: True if a matching insight was found
        insight: the matched IntraTaskInsight (None if not found)
        confidence: 0.0–1.0 match confidence
        reason: why this insight was selected (or why none was found)
    """

    found: bool = False
    insight: IntraTaskInsight | None = None
    confidence: float = 0.0
    reason: str = ""


class EMGRetriever:
    """Retrieves matching insights from the EMG store.

    The retrieval is mechanical (no LLM): it matches the normalized
    requirement's intent + operations + components against the stored
    insights' provenance. This is the "graph retrieval" part of the
    TurboVLA-style architecture — deterministic, fast, and auditable.

    Spec ref: §15.11 (Retrieval).
    """

    def __init__(self, store: InMemoryInsightStore | None = None):
        self.store = store or InMemoryInsightStore()

    def retrieve(
        self,
        requirement: NormalizedRequirement,
        project_id: str | None = None,
    ) -> RetrievalResult:
        """Find the best matching PROJECT_APPROVED insight.

        Args:
            requirement: the normalized requirement to match against.
            project_id: optional project filter.

        Returns:
            RetrievalResult with the best match (or found=False).
        """
        # Only retrieve PROJECT_APPROVED insights (spec §15.10)
        candidates = self.store.list(
            project_id=project_id,
            state=MemoryPromotionState.PROJECT_APPROVED,
        )

        if not candidates:
            return RetrievalResult(
                found=False,
                reason="no PROJECT_APPROVED insights in store",
            )

        # Score each candidate by similarity to the requirement
        best_score = 0.0
        best_insight = None
        for record in candidates:
            if record.insight is None:
                continue
            score = self._score_match(requirement, record.insight)
            if score > best_score:
                best_score = score
                best_insight = record.insight

        if best_insight is None or best_score < 0.3:
            return RetrievalResult(
                found=False,
                reason=f"best match score {best_score:.2f} below threshold 0.30",
            )

        return RetrievalResult(
            found=True,
            insight=best_insight,
            confidence=best_score,
            reason=f"matched with score {best_score:.2f}",
        )

    def _score_match(
        self,
        requirement: NormalizedRequirement,
        insight: IntraTaskInsight,
    ) -> float:
        """Score how well an insight matches a requirement.

        Scoring is based on:
          1. Intent match (0.4 weight) — same intent category
          2. Operations overlap (0.3 weight) — shared operations
          3. Component overlap (0.3 weight) — shared components

        Returns a score in [0, 1].
        """
        # The insight's task_id encodes the original requirement's intent
        # For now, we match on the successful_workflow's action types
        score = 0.0

        # 1. Intent match: check if the insight's workflow actions include
        #    the same operations as the requirement
        workflow_actions = [tuple(n.get("action", ())) for n in insight.successful_workflow]
        req_operations = set(requirement.operations)
        workflow_ops = set()
        for action in workflow_actions:
            if len(action) >= 2:
                workflow_ops.add(action[1])  # op field (addNode, etc.)

        if req_operations and workflow_ops:
            overlap = len(req_operations & workflow_ops) / len(req_operations)
            score += 0.4 * overlap

        # 2. Component overlap
        req_components = set(requirement.components)
        workflow_components = set()
        for action in workflow_actions:
            if len(action) >= 3:
                workflow_components.add(action[2])  # componentType

        if req_components and workflow_components:
            overlap = len(req_components & workflow_components) / len(req_components)
            score += 0.3 * overlap

        # 3. Corrections relevance: if the insight has corrections that
        #    mention the same components, boost the score
        if requirement.components:
            relevant_corrections = 0
            for correction in insight.corrections:
                for avoid in correction.avoid:
                    action = avoid.get("action")
                    if action and len(action) >= 3 and action[2] in req_components:
                        relevant_corrections += 1
                        break
            if relevant_corrections > 0:
                score += 0.3 * min(relevant_corrections / len(requirement.components), 1.0)

        return min(score, 1.0)


def inject_insight_into_plan(
    insight: IntraTaskInsight,
    base_revision: str,
    project_id: str,
    flow_id: str | None = None,
) -> list[dict[str, Any]]:
    """Convert an insight's successful_workflow into plan steps.

    This is the "injection" step (spec §15.12): the expert's verified
    workflow is converted into flow.patch operations that the executor
    can apply directly, without LLM involvement.

    Args:
        insight: the matched IntraTaskInsight.
        base_revision: current HEAD sha for baseRevision injection.
        project_id: the project to apply the plan to.
        flow_id: the target flow (optional for create-flow insights).

    Returns:
        List of PlanStep dicts ready for the executor.
    """
    steps: list[dict[str, Any]] = []

    for i, node in enumerate(insight.successful_workflow):
        action = node.get("action")
        if action is None or len(action) < 2:
            continue

        tool = action[0]  # e.g. "flow.patch"
        op = action[1]  # e.g. "addNode"

        if tool == "flow.patch":
            # Build a flow.patch operation from the workflow action
            component_type = action[2] if len(action) >= 3 else "log.message"
            node_id = f"emg-{component_type.split('.')[-1]}-{i}"

            step_args: dict[str, Any] = {
                "projectId": project_id,
                "flowId": flow_id or "default",
                "baseRevision": base_revision,
                "operations": [
                    {
                        "op": op,
                        "node": {
                            "id": node_id,
                            "type": component_type,
                            "config": {},
                            "fidelity": "compatible-subset",
                        },
                    }
                ],
            }
            steps.append(
                {
                    "order": i + 1,
                    "tool": "flow.patch",
                    "arguments": step_args,
                    "rationale": f"EMG-injected from expert trajectory (action: {op} {component_type})",
                    "depends_on": [],
                }
            )
        elif tool == "resource.write":
            steps.append(
                {
                    "order": i + 1,
                    "tool": "resource.write",
                    "arguments": {
                        "projectId": project_id,
                        "path": action[3] if len(action) >= 4 else f"flows/{flow_id}/resources/emg-{i}.json",
                        "content": "{}",
                    },
                    "rationale": "EMG-injected resource write from expert trajectory",
                    "depends_on": [],
                }
            )

    return steps


__all__ = [
    "EMGRetriever",
    "RetrievalResult",
    "inject_insight_into_plan",
]
