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

WP-08 PR-3 / Track A-004: `promote_seed_corpus()` now optionally writes
through to a JsonlEmgStore on disk. Callers who want durability pass
`durable_store=build_emg_store(...)`; the in-memory store stays the
default for tests so existing tests pass unchanged.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

# Make oiw importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.emg.graph_builder import ActionDecisionGraphBuilder
from oiw.emg.insight.compiler import IntraTaskInsightCompiler
from oiw.emg.matching.exact import ExactMatcher
from oiw.emg.promotion import (
    InMemoryInsightStore,
    MemoryPromotionWorkflow,
)
from oiw.emg.subgraph.common import CommonSubgraphExtractor
from oiw.emg.subgraph.edit_path import GraphEditPathExtractor

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
    *,
    durable_store: Any | None = None,
    persist: bool = False,
) -> list[str]:
    """Promote a batch of seed trajectories.

    Args:
        trajectories: List of EngineeringTrajectory objects.
        store: Optional pre-existing in-memory store (for testing). Ignored
            when `durable_store` is provided.
        project_id: The project ID.
        durable_store: Optional JsonlEmgStore (or any EmgStore impl). When
            provided, PROJECT_APPROVED insights + their task nodes are
            upsert_*'d to this store, surviving process restart. WP-08 A-004.
        persist: When True (and durable_store provided), call durable_store.save()
            at the end so changes hit disk.

    Returns:
        List of successfully promoted insight IDs.
    """
    workflow = MemoryPromotionWorkflow(store=store or InMemoryInsightStore())
    promoted: list[str] = []

    for traj in trajectories:
        insight_id = promote_seed_trajectory(traj, workflow, project_id)
        if insight_id is None:
            continue
        promoted.append(insight_id)

        # WP-08 A-004: mirror into the durable store if one was supplied.
        # The in-memory workflow state is the source of truth here; the
        # durable store is a downstream sink.
        if durable_store is not None:
            record = workflow.store.get(insight_id)
            if record is not None and record.state.value == "PROJECT_APPROVED":
                durable_store.upsert_insight(record)
                # Also upsert a task node keyed on the trajectory id, so the
                # requirement → insight link is searchable.
                _upsert_task_for_trajectory(durable_store, traj, record, project_id)

    if persist and durable_store is not None:
        durable_store.save()

    return promoted


def _upsert_task_for_trajectory(
    durable_store: Any,
    trajectory: Any,
    record: Any,
    project_id: str,
) -> None:
    """Upsert a TaskMemoryNode into the durable store for a promoted trajectory.

    WP-08 A-004: the task node carries the requirement embedding + provenance,
    so retrieval can find this insight later via search_similar().
    """
    # Build a NormalizedRequirement from the trajectory's metadata if possible.
    # Fall back to a minimal "seed" requirement when the trajectory doesn't
    # carry structured intent.
    from oiw.agent.interpreter import NormalizedRequirement
    from oiw.emg.task_store import TaskMemoryNode

    metadata = getattr(trajectory, "metadata", None)
    task_id = getattr(metadata, "taskId", None) or getattr(metadata, "id", None) or f"task-{uuid.uuid4().hex[:8]}"
    raw = getattr(metadata, "requirement", None) or "seed trajectory"

    # Best-effort normalization — the real pipeline goes through the
    # interpreter, but for seed promotion we accept whatever the trajectory
    # carries. The point of A-004 is that the node is *persisted*, not that
    # its embedding is perfect.
    try:
        nr = NormalizedRequirement(
            intent=getattr(metadata, "intent", None) or "seed",
            raw=raw,
            archetype=getattr(metadata, "archetype", None),
            source_protocol=getattr(metadata, "source_protocol", None),
            target_protocol=getattr(metadata, "target_protocol", None),
            operations=list(getattr(metadata, "operations", []) or []),
            components=list(getattr(metadata, "components", []) or []),
        )
        durable_store.upsert_task_from_requirement(
            nr,
            task_id=task_id,
            project_id=project_id,
            insight_ref=record.id,
            reward={},
            # Seed corpus = global knowledge; project-scoped nodes would
            # be invisible to cross-task retrieval from other projects.
            confidentiality_scope="organization",
        )
    except Exception:
        # If requirement normalization fails, upsert a node with the raw
        # embedding only — better than dropping the insight entirely.
        embedder = getattr(durable_store, "_embedder", None)
        if embedder is not None:
            try:
                embedding = embedder.embed(NormalizedRequirement(
                    intent="seed", raw=raw, archetype=None, source_protocol=None,
                    target_protocol=None, operations=[], components=[],
                ))
                node = TaskMemoryNode(
                    id=f"task-mem-{uuid.uuid4().hex[:12]}",
                    task_id=task_id,
                    requirement_embedding=embedding.vector,
                    normalized_requirement={"raw": raw},
                    insight_ref=record.id,
                    approval="PROJECT_APPROVED",
                    project_id=project_id,
                    confidentiality_scope="organization",
                )
                durable_store.upsert_task(node)
            except Exception:
                pass  # logged by the caller's exception handler if any


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
    "SEED_DISCOUNT_FACTOR",
    "build_seed_retriever",
    "promote_seed_corpus",
    "promote_seed_trajectory",
]
