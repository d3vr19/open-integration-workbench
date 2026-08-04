"""Trajectory pairer — links failed + expert trajectories and extracts edit paths (WP-07 Task B-001).

Pairs the failed trajectory with the expert trajectory, builds ADGs for
both, runs graph matching, and extracts the edit path (the correction
knowledge). The edit path is stored as a correction insight in the EMG.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Make oiw importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from .session import LearningSession, LearningSessionStatus  # noqa: E402


class TrajectoryPairer:
    """Pairs failed + expert trajectories and extracts the edit path.

    Uses the existing EMG infrastructure:
      - ActionDecisionGraphBuilder (builds ADGs from trajectories)
      - ExactMatcher + RuleBasedMatcher (finds correspondences)
      - CommonSubgraphExtractor (finds what was already correct)
      - GraphEditPathExtractor (finds what needs to change)
      - IntraTaskInsightCompiler (compiles into a correction insight)
    """

    def pair(
        self,
        session: LearningSession,
        failed_trajectory: Any,
        expert_trajectory: Any,
    ) -> LearningSession:
        """Pair the failed and expert trajectories.

        Args:
            session: The learning session to update.
            failed_trajectory: EngineeringTrajectory from the failed attempt.
            expert_trajectory: EngineeringTrajectory from the corrected attempt.

        Returns:
            Updated session with status=PAIRED.
        """
        from oiw.emg.graph_builder import ActionDecisionGraphBuilder  # noqa: E402
        from oiw.emg.matching.exact import ExactMatcher  # noqa: E402
        from oiw.emg.matching.rule_based import RuleBasedMatcher  # noqa: E402
        from oiw.emg.subgraph.common import CommonSubgraphExtractor  # noqa: E402
        from oiw.emg.subgraph.edit_path import GraphEditPathExtractor  # noqa: E402

        # Build ADGs for both trajectories
        builder = ActionDecisionGraphBuilder()
        failed_adg = builder.build(failed_trajectory)
        expert_adg = builder.build(expert_trajectory)

        # Run cascading matcher
        exact = ExactMatcher().match(failed_adg, expert_adg)
        rule = RuleBasedMatcher().match(failed_adg, expert_adg, exact)

        # Extract common subgraph + edit path
        common = CommonSubgraphExtractor().extract(failed_adg, expert_adg, rule)
        GraphEditPathExtractor().extract(failed_adg, expert_adg, rule, common)

        # Store the edit path
        session.edit_path_id = f"editpath-{session.id}"
        session.status = LearningSessionStatus.PAIRED

        return session

    def extract(
        self,
        session: LearningSession,
        failed_trajectory: Any,
        expert_trajectory: Any,
    ) -> tuple[LearningSession, Any]:
        """Extract the correction insight from the paired trajectories.

        Returns (updated_session, insight).
        """
        from oiw.emg.graph_builder import ActionDecisionGraphBuilder  # noqa: E402
        from oiw.emg.insight.compiler import IntraTaskInsightCompiler  # noqa: E402
        from oiw.emg.matching.exact import ExactMatcher  # noqa: E402
        from oiw.emg.matching.rule_based import RuleBasedMatcher  # noqa: E402
        from oiw.emg.subgraph.common import CommonSubgraphExtractor  # noqa: E402
        from oiw.emg.subgraph.edit_path import GraphEditPathExtractor  # noqa: E402

        builder = ActionDecisionGraphBuilder()
        failed_adg = builder.build(failed_trajectory)
        expert_adg = builder.build(expert_trajectory)

        exact = ExactMatcher().match(failed_adg, expert_adg)
        rule = RuleBasedMatcher().match(failed_adg, expert_adg, exact)
        common = CommonSubgraphExtractor().extract(failed_adg, expert_adg, rule)
        edit_path = GraphEditPathExtractor().extract(failed_adg, expert_adg, rule, common)

        insight = IntraTaskInsightCompiler().compile(
            task_id=session.id,
            exploration=failed_adg,
            expert=expert_adg,
            common=common,
            edit_path=edit_path,
            match_stage=rule.stage,
        )

        session.insight_id = insight.task_id
        session.status = LearningSessionStatus.EXTRACTED

        return session, insight


__all__ = ["TrajectoryPairer"]
