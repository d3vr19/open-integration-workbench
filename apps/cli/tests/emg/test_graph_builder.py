"""Tests for the Action Decision Graph builder (WP-05 Task 8).

Covers:
  - Build ADG from 3-step trajectory → 4 nodes (INIT + 3 actions)
  - Node reuse: same action twice → 1 node, 2 incoming edges
  - Edge labels include normalized observation
  - Uninformative observations don't advance prev_node
  - Graph is deterministic for same trajectory
"""

from __future__ import annotations

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


def _make_trajectory(steps: list[TrajectoryStep]) -> EngineeringTrajectory:
    return EngineeringTrajectory(
        metadata=TrajectoryMetadata(
            id="traj-test",
            projectId="test",
            taskId="task-test",
            baseRevision="abc123",
            startedAt=1000.0,
        ),
        spec=TrajectorySpec(steps=steps),
    )


def _make_step(
    index: int,
    normalized: tuple = ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single-required"),
    obs_type: str = "pre-action",
) -> TrajectoryStep:
    return TrajectoryStep(
        index=index,
        observation=ObservationRecord(
            type=obs_type,
            fingerprint="fp" + str(index),
            summary={"step": index},
        ),
        action=ActionRecord(
            type="flow.patch",
            normalized=normalized,
            argumentsDigest="digest" + str(index),
        ),
        result=ResultRecord(status="applied", summary="ok"),
    )


def test_build_adg_3_step_trajectory() -> None:
    """3-step trajectory with distinct actions → 4 nodes (INIT + 3), 3 edges."""
    normalizeds = [
        ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single-required"),
        ("resource.write", "add-resource", "schema.json", "flows/order-to-s4/...", ""),
        ("test.create", "add-test", "flow-test", "order-to-s4", ""),
    ]
    steps = [_make_step(i, normalized=normalizeds[i]) for i in range(3)]
    trajectory = _make_trajectory(steps)
    adg = ActionDecisionGraphBuilder().build(trajectory)

    assert adg.trajectory_id == "traj-test"
    assert adg.node_count == 4  # INIT + 3 distinct actions
    assert adg.edge_count == 3
    assert "INIT" in adg.graph.nodes


def test_node_reuse_same_action_twice() -> None:
    """Same normalized action twice → 1 action node, 2 incoming edges."""
    steps = [_make_step(0), _make_step(1)]
    trajectory = _make_trajectory(steps)
    adg = ActionDecisionGraphBuilder().build(trajectory)

    assert adg.node_count == 2  # INIT + 1 reused action
    assert adg.edge_count == 2


def test_edge_labels_include_observation() -> None:
    """Edges carry the normalized observation label + step_index."""
    trajectory = _make_trajectory([_make_step(0)])
    adg = ActionDecisionGraphBuilder().build(trajectory)

    edges = list(adg.graph.edges(data=True))
    assert len(edges) == 1
    _, _, data = edges[0]
    assert "observation" in data
    assert "step_index" in data


def test_uninformative_observations_dont_advance() -> None:
    """repeated-failure observations don't advance prev_node."""
    steps = [
        _make_step(0, obs_type="pre-action"),
        _make_step(
            1,
            normalized=("flow.patch", "addNode", "log.message", "add-log", "single"),
            obs_type="repeated-failure",
        ),
    ]
    trajectory = _make_trajectory(steps)
    adg = ActionDecisionGraphBuilder().build(trajectory)

    assert adg.node_count == 3  # INIT + 2 actions
    edges = list(adg.graph.edges(data=True))
    # Second edge should come FROM the first action node (not INIT)
    assert edges[1][0] != "INIT"


def test_graph_is_deterministic() -> None:
    """Same trajectory → same graph."""
    trajectory = _make_trajectory([_make_step(0), _make_step(1)])
    builder = ActionDecisionGraphBuilder()
    adg1 = builder.build(trajectory)
    adg2 = builder.build(trajectory)

    assert adg1.node_count == adg2.node_count
    assert set(adg1.graph.nodes) == set(adg2.graph.nodes)
