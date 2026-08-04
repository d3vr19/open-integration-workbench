"""Tests for the synthetic expert trajectory generator (WP-06 Task A-003).

Covers:
  - Synthesize trajectory from order-to-s4 reference scenario
  - Correct step count and action types
  - Generated requirement description is non-empty
  - Normalized requirement has correct intent and operations
  - Reward vector has correct dimensions
  - Trajectory persists to YAML and can be loaded back
"""

from __future__ import annotations

import sys
from pathlib import Path


# Make packages importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # seed-corpus dir itself

from synthesize_trajectory import (  # noqa: E402
    synthesize_expert_trajectory,
)

EXAMPLE_ORDER = REPO_ROOT / "examples" / "order-to-s4" / "flows" / "order-to-s4"
EXAMPLE_SFTP = REPO_ROOT / "examples" / "sftp-order-drop" / "flows" / "batch-orders"


class TestSynthesizeTrajectory:
    def test_synthesize_from_order_to_s4(self) -> None:
        """Synthesize trajectory from order-to-s4 reference scenario."""
        traj = synthesize_expert_trajectory(EXAMPLE_ORDER)

        assert traj.metadata.id == "seed-order-to-s4"
        assert traj.metadata.projectId == "seed-corpus"
        assert traj.spec.outcome.status == "success"
        assert len(traj.spec.steps) > 0

        # First step should be flow.create
        first_action = traj.spec.steps[0].action
        assert first_action.type == "flow.create"

        # Last step should be build.export
        last_action = traj.spec.steps[-1].action
        assert last_action.type == "build.export"

    def test_correct_action_types_present(self) -> None:
        """Trajectory contains flow.create, flow.patch, and flow.validate steps."""
        traj = synthesize_expert_trajectory(EXAMPLE_ORDER)
        action_types = {s.action.type for s in traj.spec.steps}

        assert "flow.create" in action_types
        assert "flow.patch" in action_types
        assert "flow.validate" in action_types
        assert "build.export" in action_types

    def test_requirement_description_non_empty(self) -> None:
        """Generated requirement description is non-empty and contains key terms."""
        traj = synthesize_expert_trajectory(EXAMPLE_ORDER)
        raw = traj.spec.query.raw

        assert len(raw) > 20
        assert "integration flow" in raw.lower()
        # Should mention at least one protocol or step type
        assert any(
            term in raw.lower()
            for term in ["http", "sftp", "soap", "receiver", "sender"]
        )

    def test_normalized_requirement_correct(self) -> None:
        """Normalized requirement has correct intent and operations."""
        traj = synthesize_expert_trajectory(EXAMPLE_ORDER)
        norm = traj.spec.query.normalized

        assert norm["intent"] == "create-flow"
        assert norm["confidence"] == 0.9
        assert "must-have-error-handling" in norm["constraints"]
        # Should have some components
        assert len(norm["components"]) > 0
        # Should have some operations
        assert len(norm["operations"]) > 0

    def test_reward_vector_has_dimensions(self) -> None:
        """Reward vector has the expected fields."""
        traj = synthesize_expert_trajectory(EXAMPLE_ORDER)
        reward = traj.spec.outcome.reward

        assert "structuralValidity" in reward
        assert "unitTests" in reward
        assert "completion" in reward
        assert "deploymentSuccess" in reward
        assert "hardGates" in reward
        # Seed artifacts have no deployment
        assert reward["deploymentSuccess"] == 0.0

    def test_synthesize_from_sftp_order_drop(self) -> None:
        """Synthesize trajectory from sftp-order-drop scenario."""
        traj = synthesize_expert_trajectory(EXAMPLE_SFTP)

        assert traj.metadata.id == "seed-batch-orders"
        assert len(traj.spec.steps) > 0
        # Should have flow.create as first step
        assert traj.spec.steps[0].action.type == "flow.create"

    def test_trajectory_steps_have_observations(self) -> None:
        """Every step has an observation + action + result."""
        traj = synthesize_expert_trajectory(EXAMPLE_ORDER)

        for step in traj.spec.steps:
            assert step.observation is not None
            assert step.action is not None
            assert step.result is not None
            assert step.action.normalized  # non-empty tuple
            assert step.action.argumentsDigest  # non-empty sha256

    def test_topological_order(self) -> None:
        """Nodes are added in topological order (senders before receivers)."""
        traj = synthesize_expert_trajectory(EXAMPLE_ORDER)

        # Find the flow.patch addNode steps
        add_node_steps = [
            s
            for s in traj.spec.steps
            if s.action.type == "flow.patch" and "addNode" in str(s.action.normalized)
        ]

        # The first addNode should be a sender or entrypoint
        if add_node_steps:
            first_node_type = add_node_steps[0].action.normalized[2]  # componentType
            # Should be a sender type or the first entrypoint
            assert (
                "sender" in first_node_type
                or "http" in first_node_type
                or first_node_type == "modifier.content"
            )
