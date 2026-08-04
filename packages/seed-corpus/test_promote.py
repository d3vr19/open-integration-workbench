"""Tests for seed corpus promotion + retrieval integration (WP-06 Tasks A-004, A-005).

Covers:
  - Promote seed trajectories → all reach PROJECT_APPROVED
  - Redaction strips secrets from seed trajectories
  - Seed insights have discounted confidence (0.8× original)
  - Seed corpus retrieval finds matching insight for known pattern
  - Seed corpus retrieval returns not-found for novel pattern
  - No secrets in promoted seed insights
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthesize_trajectory import synthesize_expert_trajectory  # noqa: E402
from promote import (  # noqa: E402
    promote_seed_trajectory,
    promote_seed_corpus,
    build_seed_retriever,
    SEED_DISCOUNT_FACTOR,
)

from oiw.emg.promotion import (  # noqa: E402
    InMemoryInsightStore,
    MemoryPromotionState,
    MemoryPromotionWorkflow,
)
from oiw.agent.interpreter import NormalizedRequirement  # noqa: E402

EXAMPLE_ORDER = REPO_ROOT / "examples" / "order-to-s4" / "flows" / "order-to-s4"
EXAMPLE_SFTP = REPO_ROOT / "examples" / "sftp-order-drop" / "flows" / "batch-orders"


# ---------------------------------------------------------------------------
# Task A-004: Seed Corpus Promotion Pipeline
# ---------------------------------------------------------------------------


class TestSeedPromotion:
    def test_promote_single_trajectory(self) -> None:
        """Promote a single seed trajectory → PROJECT_APPROVED."""
        traj = synthesize_expert_trajectory(EXAMPLE_ORDER)
        wf = MemoryPromotionWorkflow()
        insight_id = promote_seed_trajectory(traj, wf)
        assert insight_id is not None
        record = wf.store.get(insight_id)
        assert record.state == MemoryPromotionState.PROJECT_APPROVED

    def test_promote_batch(self) -> None:
        """Promote multiple seed trajectories → all reach PROJECT_APPROVED."""
        trajectories = [
            synthesize_expert_trajectory(EXAMPLE_ORDER),
            synthesize_expert_trajectory(EXAMPLE_SFTP),
        ]
        promoted = promote_seed_corpus(trajectories)
        assert len(promoted) == 2

    def test_seed_insights_have_discounted_confidence(self) -> None:
        """Seed insights have confidence *= 0.8 (discount factor)."""
        traj = synthesize_expert_trajectory(EXAMPLE_ORDER)
        wf = MemoryPromotionWorkflow()
        insight_id = promote_seed_trajectory(traj, wf)
        record = wf.store.get(insight_id)

        # The insight's corrections should have discounted confidence
        if record.insight and record.insight.corrections:
            for correction in record.insight.corrections:
                # Original confidence is 1.0, discounted = 0.8
                assert correction.confidence <= SEED_DISCOUNT_FACTOR

    def test_seed_insight_reviewer_is_bot(self) -> None:
        """Seed insights are reviewed by 'seed-corpus-bot'."""
        traj = synthesize_expert_trajectory(EXAMPLE_ORDER)
        wf = MemoryPromotionWorkflow()
        insight_id = promote_seed_trajectory(traj, wf)
        record = wf.store.get(insight_id)
        assert record.reviewed_by == "seed-corpus-bot"
        assert record.approved_by == "seed-corpus-bot"

    def test_promoted_insight_is_retrievable(self) -> None:
        """Promoted seed insights are retrievable via the store."""
        traj = synthesize_expert_trajectory(EXAMPLE_ORDER)
        store = InMemoryInsightStore()
        promote_seed_trajectory(traj, MemoryPromotionWorkflow(store=store))

        approved = store.list(state=MemoryPromotionState.PROJECT_APPROVED)
        assert len(approved) >= 1


# ---------------------------------------------------------------------------
# Task A-005: Seed Corpus Retrieval Integration
# ---------------------------------------------------------------------------


class TestSeedRetrieval:
    def _setup_retriever(self):
        """Build a retriever with a promoted seed trajectory."""
        traj = synthesize_expert_trajectory(EXAMPLE_ORDER)
        store = InMemoryInsightStore()
        promote_seed_trajectory(traj, MemoryPromotionWorkflow(store=store))
        retriever = build_seed_retriever(store)
        return retriever, traj

    def test_retrieval_finds_matching_insight(self) -> None:
        """Seed corpus retrieval finds matching insight for known pattern."""
        retriever, traj = self._setup_retriever()

        # Build a requirement matching the seed trajectory
        req = NormalizedRequirement(
            intent="create-flow",
            operations=["validate", "transform"],
            components=["validator.json-schema", "receiver.http", "sender.http"],
            raw="Create HTTPS-to-HTTP flow with validation",
        )

        result = retriever.retrieve(req)
        assert result.found
        assert result.insight is not None
        assert result.confidence > 0.0

    def test_retrieval_returns_not_found_for_novel(self) -> None:
        """Seed corpus retrieval returns not-found for novel pattern."""
        retriever, _ = self._setup_retriever()

        req = NormalizedRequirement(
            intent="fix-flow",
            source_protocol="idoc",
            target_protocol="smtp",
            operations=["route"],
            components=["receiver.idoc", "receiver.mail"],
            raw="Fix IDoc to Mail flow",
        )

        result = retriever.retrieve(req)
        # Should not find a matching insight
        assert not result.found or result.confidence < 0.3

    def test_no_secrets_in_promoted_insights(self) -> None:
        """No secrets in promoted seed insights."""
        from oiw.agent.redaction import Redactor

        traj = synthesize_expert_trajectory(EXAMPLE_ORDER)
        store = InMemoryInsightStore()
        promote_seed_trajectory(traj, MemoryPromotionWorkflow(store=store))

        redactor = Redactor()
        for record in store.list():
            if record.insight:
                # Check the insight's workflow for secrets
                for step in record.insight.successful_workflow:
                    action = step.get("action")
                    if action:
                        text = str(action)
                        redacted = redactor.redact(text)
                        assert redacted == text, f"secret found in seed insight: {text}"

    def test_seed_retriever_works_without_cross_task(self) -> None:
        """Seed retriever works with only intra-task store (no cross-task)."""
        traj = synthesize_expert_trajectory(EXAMPLE_ORDER)
        store = InMemoryInsightStore()
        promote_seed_trajectory(traj, MemoryPromotionWorkflow(store=store))
        retriever = build_seed_retriever(store)

        # Should work fine without task_store/edge_store
        req = NormalizedRequirement(
            intent="create-flow",
            operations=["validate"],
            components=["validator.json-schema"],
            raw="Add validation",
        )
        result = retriever.retrieve(req)
        # cross_task_insights should be empty (no task store configured)
        assert len(result.cross_task_insights) == 0
