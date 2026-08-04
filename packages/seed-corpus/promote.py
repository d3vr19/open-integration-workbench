"""Seed corpus promotion pipeline (WP-06 Task A-004).

Spec ref: §15.14 (Seed Corpus), §15.10 (Memory Promotion).

Auto-promotes synthesized seed trajectories through the full promotion
workflow: CAPTURED → REDACTED → OUTCOME_VERIFIED → MATCHED →
INSIGHT_GENERATED → REVIEWED → PROJECT_APPROVED.

The seed corpus bypasses human review because:
  - All artifacts are public and license-audited
  - All trajectories are synthesized from verified artifacts
  - The promotion is recorded with provenance.source = "seed-corpus"
  - Seed insights have confidence *= 0.8 (discount for synthetic origin)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Make oiw importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.emg.graph_builder import ActionDecisionGraphBuilder  # noqa: E402
from oiw.emg.insight.compiler import IntraTaskInsightCompiler  # noqa: E402
from oiw.emg.matching.exact import ExactMatcher  # noqa: E402
from oiw.emg.promotion import (  # noqa: E402
    InMemoryInsightStore,
    MemoryPromotionWorkflow,
)
from oiw.emg.subgraph.common import CommonSubgraphExtractor  # noqa: E402
from oiw.emg.subgraph.edit_path import GraphEditPathExtractor  # noqa: E402


SEED_DISCOUNT_FACTOR = 0.8


def promote_seed_trajectory(
    trajectory: Any,
    workflow: MemoryPromotionWorkflow,
    project_id: str = "seed-corpus",
) -> str | None:
    """Promote a single seed trajectory through the full pipeline.

    Args:
        trajectory: An EngineeringTrajectory (from synthesize_expert_trajectory).
        workflow: The MemoryPromotionWorkflow to use.
        project_id: The project ID for the insight record.

    Returns:
        The insight ID if successfully promoted to PROJECT_APPROVED,
        None if promotion failed.
    """
    # 1. CAPTURED
    record = workflow.record(
        trajectory_id=trajectory.metadata.id,
        project_id=project_id,
        insight=None,
    )

    # 2. REDACTED — trajectory is already redacted by TrajectoryRecorder
    workflow.redact(record.id)

    # 3. OUTCOME_VERIFIED — seed artifacts pass validation + tests by construction
    workflow.verify_outcome(record.id, tests_pass=True, deploy_success=True)

    # 4. MATCHED — build ADG and run exact matcher against self
    adg = ActionDecisionGraphBuilder().build(trajectory)
    match = ExactMatcher().match(adg, adg)  # self-match = 100% confidence
    workflow.match(record.id)

    # 5. INSIGHT_GENERATED — compile intra-task insight
    common = CommonSubgraphExtractor().extract(adg, adg, match)
    edit_path = GraphEditPathExtractor().extract(adg, adg, match, common)
    insight = IntraTaskInsightCompiler().compile(
        task_id=trajectory.metadata.taskId or trajectory.metadata.id,
        exploration=adg,
        expert=adg,
        common=common,
        edit_path=edit_path,
        match_stage="exact",
    )

    # Apply seed discount factor
    for correction in insight.corrections:
        correction.confidence *= SEED_DISCOUNT_FACTOR

    workflow.generate_insight(record.id, insight=insight)

    # 6. REVIEWED — auto-approve for seed corpus
    workflow.review(record.id, reviewer="seed-corpus-bot")

    # 7. PROJECT_APPROVED — auto-approve for seed corpus
    workflow.approve_project(record.id, approver="seed-corpus-bot")

    return record.id


def promote_seed_corpus(
    trajectories: list[Any],
    store: InMemoryInsightStore | None = None,
    project_id: str = "seed-corpus",
) -> list[str]:
    """Promote a batch of seed trajectories.

    Args:
        trajectories: List of EngineeringTrajectory objects.
        store: Optional pre-existing store (for testing).
        project_id: The project ID.

    Returns:
        List of successfully promoted insight IDs.
    """
    workflow = MemoryPromotionWorkflow(store=store or InMemoryInsightStore())
    promoted: list[str] = []

    for traj in trajectories:
        insight_id = promote_seed_trajectory(traj, workflow, project_id)
        if insight_id is not None:
            promoted.append(insight_id)

    return promoted


def build_seed_retriever(
    store: InMemoryInsightStore,
    task_store: Any = None,
    edge_store: Any = None,
) -> Any:
    """Build an EMGRetriever pre-configured with the seed corpus store.

    Args:
        store: The insight store populated with seed trajectories.
        task_store: Optional TaskMemoryNodeStore for cross-task retrieval.
        edge_store: Optional CrossTaskEdgeStore for cross-task edges.

    Returns:
        EMGRetriever configured for seed corpus retrieval.
    """
    from oiw.emg.retrieval import EMGRetriever

    return EMGRetriever(
        store=store,
        task_store=task_store,
        edge_store=edge_store,
    )


__all__ = [
    "promote_seed_trajectory",
    "promote_seed_corpus",
    "build_seed_retriever",
    "SEED_DISCOUNT_FACTOR",
]
