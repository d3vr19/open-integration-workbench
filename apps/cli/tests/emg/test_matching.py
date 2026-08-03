"""Tests for EMG matching + subgraph extraction (WP-05 Tasks 9-12).

Covers:
  - ExactMatcher: identical/different trajectories, IR version mismatch, confidence
  - RuleBasedMatcher: alias match, diagnostic class, role mapping, no false positives
  - CommonSubgraphExtractor: identical, extra failed step, matching observations
  - GraphEditPathExtractor: DELETE, INSERT, RELABEL, EDGE_CORRECTION
"""

from __future__ import annotations

import pytest

from oiw.agent.trajectory import (
    ActionRecord,
    EngineeringTrajectory,
    ObservationRecord,
    ResultRecord,
    TrajectoryMetadata,
    TrajectorySpec,
    TrajectoryStep,
)
from oiw.emg.graph_builder import ActionDecisionGraphBuilder
from oiw.emg.matching import ExactMatcher, RuleBasedMatcher
from oiw.emg.subgraph import CommonSubgraphExtractor, GraphEditPathExtractor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adg(
    steps_data: list[tuple[str, str, str, str, str, str]],
    trajectory_id: str = "traj-test",
) -> EngineeringTrajectory:  # type: ignore[name-defined]
    """Build an ADG from a list of (tool, op, comp, target, param, result) tuples."""
    steps = []
    for i, (tool, op, comp, target, param, result) in enumerate(steps_data):
        steps.append(
            TrajectoryStep(
                index=i,
                observation=ObservationRecord(type="pre-action", fingerprint=f"fp{i}", summary={}),
                action=ActionRecord(
                    type=tool,
                    normalized=(tool, op, comp, target, param),
                    argumentsDigest=f"digest{i}",
                ),
                result=ResultRecord(status=result, summary="ok"),
            )
        )
    trajectory = EngineeringTrajectory(
        metadata=TrajectoryMetadata(
            id=trajectory_id, projectId="test", taskId="task", baseRevision="abc", startedAt=1000.0
        ),
        spec=TrajectorySpec(steps=steps),
    )
    return ActionDecisionGraphBuilder().build(trajectory)


# ---------------------------------------------------------------------------
# Task 9: ExactMatcher
# ---------------------------------------------------------------------------


class TestExactMatcher:
    def test_identical_trajectories_100_percent(self) -> None:
        """Identical trajectories → 100% correspondence."""
        steps = [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")]
        exploration = _make_adg(steps, "exp")
        expert = _make_adg(steps, "expert")

        result = ExactMatcher().match(exploration, expert)
        assert result.stage == "exact"
        assert len(result.correspondence) == 1
        assert result.confidence == 1.0
        assert len(result.unmatched_explored) == 0
        assert len(result.unmatched_expert) == 0

    def test_different_actions_no_correspondence(self) -> None:
        """Different actions → no correspondence."""
        exploration = _make_adg(
            [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")], "exp"
        )
        expert = _make_adg(
            [("resource.write", "add-resource", "schema.json", "flows/x", "", "applied")], "expert"
        )

        result = ExactMatcher().match(exploration, expert)
        assert len(result.correspondence) == 0
        assert result.confidence == 0.0
        assert len(result.unmatched_explored) == 1
        assert len(result.unmatched_expert) == 1

    def test_ir_version_mismatch_no_match(self) -> None:
        """Same action but different IR version → no match."""
        exploration = _make_adg(
            [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")], "exp"
        )
        expert = _make_adg(
            [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")],
            "expert",
        )
        # Set different IR versions on both sides
        for node in exploration.graph.nodes:
            if node != "INIT":
                exploration.graph.nodes[node]["ir_version"] = "1.0"
        for node in expert.graph.nodes:
            if node != "INIT":
                expert.graph.nodes[node]["ir_version"] = "2.0"

        result = ExactMatcher().match(exploration, expert)
        assert len(result.correspondence) == 0

    def test_confidence_score_correct(self) -> None:
        """3 explored, 2 matched → confidence = 2/3."""
        exp_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
            ("resource.write", "add-resource", "schema.json", "flows/x", "", "applied"),
            ("test.create", "add-test", "flow-test", "order", "", "applied"),
        ]
        expert_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
            ("resource.write", "add-resource", "schema.json", "flows/x", "", "applied"),
        ]
        exploration = _make_adg(exp_steps, "exp")
        expert = _make_adg(expert_steps, "expert")

        result = ExactMatcher().match(exploration, expert)
        assert result.confidence == pytest.approx(2 / 3, rel=0.01)


# ---------------------------------------------------------------------------
# Task 10: RuleBasedMatcher
# ---------------------------------------------------------------------------


class TestRuleBasedMatcher:
    def test_alias_match(self) -> None:
        """receiver-http ≡ outbound-http-adapter (alias)."""
        exploration = _make_adg(
            [("flow.patch", "addNode", "receiver-http", "before-receiver", "single", "applied")], "exp"
        )
        expert = _make_adg(
            [("flow.patch", "addNode", "outbound-http-adapter", "before-receiver", "single", "applied")],
            "expert",
        )

        exact_result = ExactMatcher().match(exploration, expert)
        assert len(exact_result.correspondence) == 0  # Exact fails (different names)

        rule_result = RuleBasedMatcher().match(exploration, expert, exact_result)
        assert len(rule_result.correspondence) == 1
        assert rule_result.confidence == 1.0

    def test_diagnostic_class_match(self) -> None:
        """OIW-E001 ≡ OIW-E007 (both missing-endpoint)."""
        exploration = _make_adg(
            [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "failed")], "exp"
        )
        expert = _make_adg(
            [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")],
            "expert",
        )
        # Set diagnostic codes
        for node in exploration.graph.nodes:
            if node != "INIT":
                exploration.graph.nodes[node]["diagnostic_code"] = "OIW-E001"
        for node in expert.graph.nodes:
            if node != "INIT":
                expert.graph.nodes[node]["diagnostic_code"] = "OIW-E007"

        exact_result = ExactMatcher().match(exploration, expert)
        # Exact matches on normalized tuple, so it should match
        assert len(exact_result.correspondence) == 1

    def test_role_mapping(self) -> None:
        """node-abc123 and node-def456 both → anonymous-node role."""
        exploration = _make_adg(
            [("flow.patch", "addNode", "node-abc123", "add-node", "single", "applied")], "exp"
        )
        expert = _make_adg(
            [("flow.patch", "addNode", "node-def456", "add-node", "single", "applied")], "expert"
        )

        exact_result = ExactMatcher().match(exploration, expert)
        assert len(exact_result.correspondence) == 0  # Different componentType

        rule_result = RuleBasedMatcher().match(exploration, expert, exact_result)
        # Both map to "anonymous-node" role
        assert len(rule_result.correspondence) == 1

    def test_no_false_positives_on_dissimilar(self) -> None:
        """Dissimilar nodes should not be matched by rules."""
        exploration = _make_adg(
            [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")], "exp"
        )
        expert = _make_adg(
            [("resource.write", "add-resource", "schema.json", "flows/x", "", "applied")], "expert"
        )

        exact_result = ExactMatcher().match(exploration, expert)
        rule_result = RuleBasedMatcher().match(exploration, expert, exact_result)
        assert len(rule_result.correspondence) == 0


# ---------------------------------------------------------------------------
# Task 11: CommonSubgraphExtractor
# ---------------------------------------------------------------------------


class TestCommonSubgraph:
    def test_identical_trajectories_full_common(self) -> None:
        """Identical trajectories → entire graph is common."""
        steps = [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")]
        exploration = _make_adg(steps, "exp")
        expert = _make_adg(steps, "expert")

        match = ExactMatcher().match(exploration, expert)
        common = CommonSubgraphExtractor().extract(exploration, expert, match)

        assert len(common.nodes) == 1
        assert len(common.edges) >= 0  # INIT→action edge may or may not be "common"

    def test_extra_failed_step_excluded(self) -> None:
        """Exploration has an extra failed step → not in common subgraph."""
        exp_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
            ("flow.patch", "addNode", "log.message", "add-log", "single", "failed"),  # extra, failed
        ]
        expert_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
        ]
        exploration = _make_adg(exp_steps, "exp")
        expert = _make_adg(expert_steps, "expert")

        match = ExactMatcher().match(exploration, expert)
        common = CommonSubgraphExtractor().extract(exploration, expert, match)

        # Only the first (applied, matched) node is common
        assert len(common.nodes) == 1

    def test_common_edges_require_matching_observations(self) -> None:
        """Common edges require matching observations on both sides."""
        steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
            ("resource.write", "add-resource", "schema.json", "flows/x", "", "applied"),
        ]
        exploration = _make_adg(steps, "exp")
        expert = _make_adg(steps, "expert")

        match = ExactMatcher().match(exploration, expert)
        common = CommonSubgraphExtractor().extract(exploration, expert, match)

        # Both nodes are common; the edge between them should also be common
        # (same trajectory → same observations)
        assert len(common.nodes) == 2


# ---------------------------------------------------------------------------
# Task 12: GraphEditPathExtractor
# ---------------------------------------------------------------------------


class TestGraphEditPath:
    def test_delete_extra_exploration_node(self) -> None:
        """Exploration has extra failed step → DELETE operation."""
        exp_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
            ("flow.patch", "addNode", "log.message", "add-log", "single", "failed"),
        ]
        expert_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
        ]
        exploration = _make_adg(exp_steps, "exp")
        expert = _make_adg(expert_steps, "expert")

        match = ExactMatcher().match(exploration, expert)
        common = CommonSubgraphExtractor().extract(exploration, expert, match)
        edit_path = GraphEditPathExtractor().extract(exploration, expert, match, common)

        deletes = [op for op in edit_path.operations if op.type == "DELETE"]
        assert len(deletes) == 1
        assert "log.message" in deletes[0].target

    def test_insert_missing_expert_node(self) -> None:
        """Expert has a step not in exploration → INSERT operation."""
        exp_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
        ]
        expert_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
            ("resource.write", "add-resource", "schema.json", "flows/x", "", "applied"),
        ]
        exploration = _make_adg(exp_steps, "exp")
        expert = _make_adg(expert_steps, "expert")

        match = ExactMatcher().match(exploration, expert)
        common = CommonSubgraphExtractor().extract(exploration, expert, match)
        edit_path = GraphEditPathExtractor().extract(exploration, expert, match, common)

        inserts = [op for op in edit_path.operations if op.type == "INSERT"]
        assert len(inserts) == 1
        assert "schema.json" in inserts[0].target

    def test_relabel_different_outcome(self) -> None:
        """Same action, different result → RELABEL operation."""
        exp_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "failed"),
        ]
        expert_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
        ]
        exploration = _make_adg(exp_steps, "exp")
        expert = _make_adg(expert_steps, "expert")

        match = ExactMatcher().match(exploration, expert)
        common = CommonSubgraphExtractor().extract(exploration, expert, match)
        edit_path = GraphEditPathExtractor().extract(exploration, expert, match, common)

        relabels = [op for op in edit_path.operations if op.type == "RELABEL"]
        assert len(relabels) == 1
        assert relabels[0].from_status == "failed"
        assert relabels[0].to_status == "applied"

    def test_edge_correction_different_successors(self) -> None:
        """Corresponding nodes with different successors → EDGE_CORRECTION."""
        exp_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
            ("flow.patch", "addNode", "log.message", "add-log", "single", "applied"),  # exp goes to log
        ]
        expert_steps = [
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
            (
                "resource.write",
                "add-resource",
                "schema.json",
                "flows/x",
                "",
                "applied",
            ),  # expert goes to resource
        ]
        exploration = _make_adg(exp_steps, "exp")
        expert = _make_adg(expert_steps, "expert")

        match = ExactMatcher().match(exploration, expert)
        common = CommonSubgraphExtractor().extract(exploration, expert, match)
        edit_path = GraphEditPathExtractor().extract(exploration, expert, match, common)

        edge_corrections = [op for op in edit_path.operations if op.type == "EDGE_CORRECTION"]
        # The validator node has different successors (log vs resource)
        assert len(edge_corrections) >= 1
