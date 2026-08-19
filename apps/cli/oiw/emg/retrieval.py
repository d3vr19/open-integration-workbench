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

from dataclasses import dataclass, field
from typing import Any

from ..agent.interpreter import NormalizedRequirement
from .avoid_patterns import AvoidPattern, AvoidPatternStore
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
        cross_task_insights: cross-task insights from Phase C (empty if not enabled)
        avoid_patterns: negative-knowledge entries that apply to this
            requirement (WP-07 Track E-002). The orchestrator surfaces
            these in the plan rationale so the agent avoids known pitfalls.
    """

    found: bool = False
    insight: IntraTaskInsight | None = None
    confidence: float = 0.0
    reason: str = ""
    cross_task_insights: list[Any] = field(default_factory=list)
    avoid_patterns: list[AvoidPattern] = field(default_factory=list)


class EMGRetriever:
    """Retrieves matching insights from the EMG store.

    The retrieval is mechanical (no LLM): it matches the normalized
    requirement's intent + operations + components against the stored
    insights' provenance. This is the "graph retrieval" part of the
    TurboVLA-style architecture — deterministic, fast, and auditable.

    When a TaskMemoryNodeStore + CrossTaskEdgeStore are provided (Phase C),
    the retriever also searches for cross-task insights — reusable patterns
    from similar but different tasks.

    Spec ref: §15.11 (Retrieval), §15.13 (Cross-Task Transfer).
    """

    def __init__(
        self,
        store: InMemoryInsightStore | None = None,
        task_store: Any = None,
        edge_store: Any = None,
        avoid_pattern_store: AvoidPatternStore | None = None,
    ):
        self.store = store or InMemoryInsightStore()
        self.task_store = task_store
        self.edge_store = edge_store
        self.avoid_pattern_store = avoid_pattern_store or AvoidPatternStore()
        # Lazy-init embedder only if task_store is provided
        self._embedder = None
        if self.task_store is not None:
            from .embedding import RequirementEmbedder

            self._embedder = RequirementEmbedder()

    def retrieve(
        self,
        requirement: NormalizedRequirement,
        project_id: str | None = None,
    ) -> RetrievalResult:
        """Find matching insights from both intra-task and cross-task memory.

        Args:
            requirement: the normalized requirement to match against.
            project_id: optional project filter.

        Returns:
            RetrievalResult with the best match (or found=False).
            If cross-task stores are configured, cross_task_insights is populated.
            If avoid_pattern_store is configured, avoid_patterns is populated
            with patterns that match the requirement's archetype / components.
        """
        # 1. Intra-task retrieval (existing Phase B behavior)
        intra_result = self._retrieve_intra_task(requirement, project_id)

        # 2. Cross-task retrieval (Phase C — only if task_store + edge_store configured)
        cross_insights: list[Any] = []
        cross_reason = "not configured"
        if self.task_store is not None and self.edge_store is not None and self._embedder is not None:
            cross_insights, cross_reason = self._retrieve_cross_task(requirement, project_id)

        # 3. Avoid-pattern retrieval (WP-07 Track E-002)
        avoid_patterns = self._retrieve_avoid_patterns(requirement)

        # 4. Merge results
        found = intra_result.found or len(cross_insights) > 0
        best_confidence = intra_result.confidence
        if cross_insights:
            best_cross = max(cross_insights, key=lambda i: i.confidence)
            best_confidence = max(best_confidence, best_cross.confidence)

        return RetrievalResult(
            found=found,
            insight=intra_result.insight,
            confidence=best_confidence,
            reason=f"intra: {intra_result.reason}; cross: {cross_reason}; "
            f"avoid: {len(avoid_patterns)} patterns matched",
            cross_task_insights=cross_insights,
            avoid_patterns=avoid_patterns,
        )

    def _retrieve_avoid_patterns(
        self,
        requirement: NormalizedRequirement,
    ) -> list[AvoidPattern]:
        """Find avoid patterns that apply to this requirement.

        Uses AvoidPatternStore.find_for_requirement to match by archetype
        and component family.
        """
        if not self.avoid_pattern_store or self.avoid_pattern_store.count() == 0:
            return []
        return self.avoid_pattern_store.find_for_requirement(
            archetype=requirement.archetype,
            components=requirement.components,
        )

    def _retrieve_intra_task(
        self,
        requirement: NormalizedRequirement,
        project_id: str | None,
    ) -> RetrievalResult:
        """Existing intra-task retrieval (Phase B).

        WP-08 PR-8: if the project-specific search returns nothing, fall back
        to a cross-project search. This is the correct behavior for seed-corpus
        insights (CodeJam artifacts, tenant-pulled artifacts) — they are global
        knowledge, not project-private. Project-scoped insights (tenant-specific
        patterns with confidentialityScope=project) still only match within
        their own project because the scoring uses the insight's components,
        which are project-specific.
        """
        # 1. Try project-specific first (preserves confidentiality scoping)
        candidates = self.store.list(
            project_id=project_id,
            state=MemoryPromotionState.PROJECT_APPROVED,
        )

        # 2. WP-08 PR-8: fall back to cross-project (seed corpus / global knowledge)
        if not candidates:
            candidates = self.store.list(
                project_id=None,
                state=MemoryPromotionState.PROJECT_APPROVED,
            )
            if candidates:
                # Log that we're using cross-project knowledge
                pass  # the reason string will reflect this below
        else:
            # Also include cross-project candidates so the scorer can pick the best
            cross_project = self.store.list(
                project_id=None,
                state=MemoryPromotionState.PROJECT_APPROVED,
            )
            # Merge, avoiding duplicates by insight id
            seen_ids = {c.id for c in candidates}
            for c in cross_project:
                if c.id not in seen_ids:
                    candidates.append(c)
                    seen_ids.add(c.id)

        if not candidates:
            return RetrievalResult(
                found=False,
                reason="no PROJECT_APPROVED insights in store",
            )

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

    def _retrieve_cross_task(
        self,
        requirement: NormalizedRequirement,
        project_id: str | None,
    ) -> tuple[list[Any], str]:
        """Retrieve cross-task insights for a requirement.

        Returns (insights, reason).
        """
        # 1. Embed the requirement
        embedding = self._embedder.embed(requirement)

        # 2. Find similar task memory nodes
        similar_nodes = self.task_store.search_similar(
            embedding=embedding.vector,
            top_k=5,
            min_similarity=0.3,
            project_id=project_id,
        )

        if not similar_nodes:
            return [], "no similar task memory nodes found"

        # 3. For each similar node, get cross-task edges
        insights: list[Any] = []
        for node, _sim in similar_nodes:
            if self.edge_store is None:
                break
            edges = self.edge_store.get_edges_for_task(
                task_id=node.task_id,
                min_confidence=0.3,
                max_edges=3,
            )
            for edge in edges:
                # Check if the insight applies to this requirement
                if self._insight_applies(edge.insight, requirement):
                    insights.append(edge.insight)

        if not insights:
            return [], f"found {len(similar_nodes)} similar nodes but no applicable cross-task insights"

        # 4. Deduplicate by insight ID
        seen_ids: set[str] = set()
        unique = []
        for ins in insights:
            if ins.id not in seen_ids:
                seen_ids.add(ins.id)
                unique.append(ins)

        # 5. Rank by confidence
        unique.sort(key=lambda i: i.confidence, reverse=True)

        return unique[:3], f"found {len(unique)} cross-task insights"

    def _insight_applies(self, insight: Any, requirement: NormalizedRequirement) -> bool:
        """Check if a cross-task insight applies to a requirement."""
        applies_when = insight.applies_when
        # Check archetype match
        if (
            applies_when.get("archetype")
            and requirement.archetype
            and applies_when["archetype"] != requirement.archetype
        ):
            return False
        # Check protocol match
        if (
            applies_when.get("sourceProtocol")
            and requirement.source_protocol
            and applies_when["sourceProtocol"] != requirement.source_protocol
        ):
            return False
        return not (
            applies_when.get("targetProtocol")
            and requirement.target_protocol
            and applies_when["targetProtocol"] != requirement.target_protocol
        )

    def _score_match(
        self,
        requirement: NormalizedRequirement,
        insight: IntraTaskInsight,
    ) -> float:
        """Score how well an insight matches a requirement.

        WP-08 PR-8: revised scoring for the held-out proof.

        Two scoring modes:
          A. Expert trajectory (no corrections): component overlap is the
             primary signal. The workflow tells you "these are the node types
             you need for this pattern." Weights: 0.7 component, 0.3 operations.
          B. Correction memory (has corrections): corrections relevance is
             the primary signal — the insight says "when you see X, avoid Y."
             Weights: 0.3 component, 0.3 operations, 0.4 corrections.

        Returns a score in [0, 1].
        """
        workflow_actions = [tuple(n.get("action", ())) for n in insight.successful_workflow]
        req_operations = set(requirement.operations)
        req_components = set(requirement.components)

        # Extract workflow component types
        workflow_components = set()
        for action in workflow_actions:
            if len(action) >= 3:
                workflow_components.add(action[2])

        # Extract workflow operation types
        workflow_ops = set()
        for action in workflow_actions:
            if len(action) >= 2:
                workflow_ops.add(action[1])

        score = 0.0

        has_corrections = len(insight.corrections) > 0

        if not has_corrections:
            # Mode A: expert trajectory — component overlap is the signal
            if req_components and workflow_components:
                overlap = len(req_components & workflow_components) / len(req_components)
                score += 0.7 * overlap
            # Small boost for operations overlap (e.g. "transform" matching addNode)
            if req_operations and workflow_ops:
                op_overlap = len(req_operations & workflow_ops) / len(req_operations)
                score += 0.3 * op_overlap
        else:
            # Mode B: correction memory — corrections are the signal
            # 1. Intent match (0.3 weight)
            if req_operations and workflow_ops:
                overlap = len(req_operations & workflow_ops) / len(req_operations)
                score += 0.3 * overlap

            # 2. Component overlap (0.3 weight)
            if req_components and workflow_components:
                overlap = len(req_components & workflow_components) / len(req_components)
                score += 0.3 * overlap

            # 3. Corrections relevance (0.4 weight)
            if req_components:
                relevant_corrections = 0
                for correction in insight.corrections:
                    for avoid in correction.avoid:
                        action = avoid.get("action")
                        if action and len(action) >= 3 and action[2] in req_components:
                            relevant_corrections += 1
                            break
                if relevant_corrections > 0:
                    score += 0.4 * min(relevant_corrections / len(requirement.components), 1.0)

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
