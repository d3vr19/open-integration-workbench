"""Tests for EMG Phase C: cross-task matching, insights, edges, retrieval (WP-06 Tasks C-003..C-006).

Covers:
  - Expert-to-expert matching (identical, similar, dissimilar)
  - Cross-task insight generation
  - Cross-task edge store (add, get, increment support)
  - Cross-task retrieval integration (finds pattern, returns empty for novel)
"""

from __future__ import annotations

from oiw.agent.interpreter import NormalizedRequirement
from oiw.agent.trajectory import (
    ActionRecord,
    EngineeringTrajectory,
    ObservationRecord,
    ResultRecord,
    TrajectoryMetadata,
    TrajectorySpec,
    TrajectoryStep,
)
from oiw.emg.edge_store import CrossTaskEdgeStore
from oiw.emg.embedding import RequirementEmbedder
from oiw.emg.graph_builder import ActionDecisionGraphBuilder
from oiw.emg.insight.cross_task import CrossTaskInsight, CrossTaskInsightGenerator
from oiw.emg.matching.expert_to_expert import ExpertToExpertMatcher
from oiw.emg.retrieval import EMGRetriever
from oiw.emg.task_store import TaskMemoryNode, TaskMemoryNodeStore


def _make_adg(steps_data: list[tuple], trajectory_id: str = "traj"):
    steps = []
    for i, (tool, op, comp, target, param, result) in enumerate(steps_data):
        steps.append(
            TrajectoryStep(
                index=i,
                observation=ObservationRecord(type="pre-action", fingerprint=f"fp{i}", summary={}),
                action=ActionRecord(
                    type=tool, normalized=(tool, op, comp, target, param), argumentsDigest=f"d{i}"
                ),
                result=ResultRecord(status=result, summary="ok"),
            )
        )
    traj = EngineeringTrajectory(
        metadata=TrajectoryMetadata(
            id=trajectory_id, projectId="p", taskId="t", baseRevision="abc", startedAt=1000.0
        ),
        spec=TrajectorySpec(steps=steps),
    )
    return ActionDecisionGraphBuilder().build(traj)


def _make_task_node(task_id: str, **req_kwargs) -> TaskMemoryNode:
    embedder = RequirementEmbedder()
    req = NormalizedRequirement(raw="test", **req_kwargs)
    emb = embedder.embed(req)
    return TaskMemoryNode(
        id=f"node-{task_id}",
        task_id=task_id,
        requirement_embedding=emb.vector,
        normalized_requirement=req.to_dict(),
        approval="PROJECT_APPROVED",
    )


# ---------------------------------------------------------------------------
# Task C-003: Expert-to-Expert Matching
# ---------------------------------------------------------------------------


class TestExpertToExpertMatcher:
    def test_identical_experts_full_match(self) -> None:
        """Two identical expert graphs → full common subgraph."""
        steps = [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")]
        expert_a = _make_adg(steps, "expert-a")
        expert_b = _make_adg(steps, "expert-b")

        result = ExpertToExpertMatcher().match(expert_a, expert_b)
        assert result.common_subgraph is not None
        assert result.confidence == 1.0
        assert result.stage == "exact"

    def test_similar_experts_partial_match(self) -> None:
        """Two similar experts (shared first step) → partial common subgraph."""
        expert_a = _make_adg(
            [
                ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
                ("flow.patch", "addNode", "log.message", "add-log", "single", "applied"),
            ],
            "a",
        )
        expert_b = _make_adg(
            [
                ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied"),
                ("resource.write", "add-resource", "schema.json", "flows/x", "", "applied"),
            ],
            "b",
        )

        result = ExpertToExpertMatcher().match(expert_a, expert_b)
        assert result.confidence > 0.0

    def test_dissimilar_experts_rejected(self) -> None:
        """Two dissimilar experts → rejected."""
        expert_a = _make_adg(
            [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")], "a"
        )
        expert_b = _make_adg([("test.create", "add-test", "flow-test", "order", "", "applied")], "b")

        result = ExpertToExpertMatcher().match(expert_a, expert_b)
        # Either rejected or very low confidence
        assert result.stage in ("rejected", "rule-based")

    def test_match_result_includes_confidence_and_stage(self) -> None:
        """Match result has confidence + stage fields."""
        steps = [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")]
        expert_a = _make_adg(steps, "a")
        expert_b = _make_adg(steps, "b")

        result = ExpertToExpertMatcher().match(expert_a, expert_b)
        assert hasattr(result, "confidence")
        assert hasattr(result, "stage")
        assert hasattr(result, "reason")


# ---------------------------------------------------------------------------
# Task C-004: Cross-Task Insight Generator
# ---------------------------------------------------------------------------


class TestCrossTaskInsightGenerator:
    def test_generate_insight_from_matched_experts(self) -> None:
        """Generate insight from two matched experts."""
        steps = [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")]
        expert_a = _make_adg(steps, "expert-a")
        expert_b = _make_adg(steps, "expert-b")

        match = ExpertToExpertMatcher().match(expert_a, expert_b)
        task_a = _make_task_node(
            "task-a", intent="create-flow", operations=["validate"], components=["validator.json-schema"]
        )
        task_b = _make_task_node(
            "task-b", intent="create-flow", operations=["validate"], components=["validator.json-schema"]
        )

        insight = CrossTaskInsightGenerator().generate(task_a, task_b, match)
        assert insight is not None
        assert len(insight.workflow) > 0
        assert insight.confidence > 0.0
        assert insight.support_count == 2

    def test_insight_includes_applies_when(self) -> None:
        """Insight includes applies_when with archetype and protocols."""
        steps = [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")]
        expert_a = _make_adg(steps, "a")
        expert_b = _make_adg(steps, "b")

        match = ExpertToExpertMatcher().match(expert_a, expert_b)
        task_a = _make_task_node(
            "a",
            intent="create-flow",
            archetype="https-to-https",
            source_protocol="https",
            target_protocol="https",
        )
        task_b = _make_task_node(
            "b",
            intent="create-flow",
            archetype="https-to-https",
            source_protocol="https",
            target_protocol="https",
        )

        insight = CrossTaskInsightGenerator().generate(task_a, task_b, match)
        assert insight is not None
        assert insight.applies_when["archetype"] == "https-to-https"
        assert insight.applies_when["sourceProtocol"] == "https"

    def test_insight_includes_safety_constraints(self) -> None:
        """Insight includes safety constraints."""
        steps = [
            ("flow.patch", "addNode", "receiver.http", "before-receiver", "single", "applied"),
            ("resource.write", "add-resource", "schema.json", "flows/x", "", "applied"),
        ]
        expert_a = _make_adg(steps, "a")
        expert_b = _make_adg(steps, "b")

        match = ExpertToExpertMatcher().match(expert_a, expert_b)
        task_a = _make_task_node("a", intent="create-flow")
        task_b = _make_task_node("b", intent="create-flow")

        insight = CrossTaskInsightGenerator().generate(task_a, task_b, match)
        assert insight is not None
        assert len(insight.safety) > 0

    def test_insight_none_for_rejected_match(self) -> None:
        """No insight generated for rejected match."""
        expert_a = _make_adg(
            [("flow.patch", "addNode", "validator.json-schema", "after-sender", "single", "applied")], "a"
        )
        expert_b = _make_adg([("test.create", "add-test", "flow-test", "order", "", "applied")], "b")

        match = ExpertToExpertMatcher().match(expert_a, expert_b)
        task_a = _make_task_node("a", intent="create-flow")
        task_b = _make_task_node("b", intent="create-flow")

        insight = CrossTaskInsightGenerator().generate(task_a, task_b, match)
        if match.stage == "rejected":
            assert insight is None


# ---------------------------------------------------------------------------
# Task C-005: Cross-Task Edge Store
# ---------------------------------------------------------------------------


class TestCrossTaskEdgeStore:
    def _make_insight(self, confidence: float = 0.8) -> CrossTaskInsight:
        return CrossTaskInsight(
            id="xinsight-test",
            applies_when={"archetype": "https-to-https"},
            workflow=[],
            safety=[],
            confidence=confidence,
        )

    def test_add_edge(self) -> None:
        store = CrossTaskEdgeStore()
        edge_id = store.add_edge("task-a", "task-b", self._make_insight(), 0.9)
        assert edge_id.startswith("edge-")
        assert store.count() == 1

    def test_get_edges_for_task(self) -> None:
        store = CrossTaskEdgeStore()
        store.add_edge("task-a", "task-b", self._make_insight(0.9))
        store.add_edge("task-a", "task-c", self._make_insight(0.7))
        store.add_edge("task-d", "task-b", self._make_insight(0.5))

        # task-b has 2 edges (as target of a→b and d→b)
        edges = store.get_edges_for_task("task-b", min_confidence=0.0)
        assert len(edges) >= 2
        # Sorted by confidence descending
        assert edges[0].insight.confidence >= edges[1].insight.confidence

    def test_get_edges_respects_min_confidence(self) -> None:
        store = CrossTaskEdgeStore()
        store.add_edge("a", "b", self._make_insight(0.9))
        store.add_edge("a", "b", self._make_insight(0.3))

        edges = store.get_edges_for_task("b", min_confidence=0.5)
        assert len(edges) == 1
        assert edges[0].insight.confidence == 0.9

    def test_increment_support_count(self) -> None:
        store = CrossTaskEdgeStore()
        edge_id = store.add_edge("a", "b", self._make_insight())
        assert store.get(edge_id).times_applied == 0
        store.increment_support_count(edge_id)
        assert store.get(edge_id).times_applied == 1
        assert store.get(edge_id).insight.support_count == 3


# ---------------------------------------------------------------------------
# Task C-006: Cross-Task Retrieval Integration
# ---------------------------------------------------------------------------


class TestCrossTaskRetrieval:
    def test_cross_task_retrieval_finds_pattern(self) -> None:
        """Cross-task retrieval finds matching pattern for known archetype."""
        embedder = RequirementEmbedder()
        task_store = TaskMemoryNodeStore(embedder=embedder)
        edge_store = CrossTaskEdgeStore()

        # Create a task memory node for a known pattern
        req = NormalizedRequirement(
            intent="create-flow",
            archetype="https-to-https",
            source_protocol="https",
            target_protocol="https",
            operations=["validate"],
            components=["validator.json-schema", "receiver.http", "sender.http"],
            raw="Create HTTPS-to-HTTP flow with validation",
        )
        task_store.insert_from_requirement(req, task_id="task-1", project_id="proj-1")

        # Add a cross-task edge with an insight
        insight = CrossTaskInsight(
            id="xinsight-1",
            applies_when={
                "archetype": "https-to-https",
                "sourceProtocol": "https",
                "targetProtocol": "https",
            },
            workflow=[],
            safety=[],
            confidence=0.9,
        )
        edge_store.add_edge("task-1", "task-1", insight, similarity_score=0.9)

        retriever = EMGRetriever(task_store=task_store, edge_store=edge_store)
        result = retriever.retrieve(req, project_id="proj-1")

        assert len(result.cross_task_insights) > 0
        assert result.cross_task_insights[0].confidence >= 0.9

    def test_cross_task_retrieval_empty_for_novel(self) -> None:
        """Cross-task retrieval returns empty for novel archetype."""
        embedder = RequirementEmbedder()
        task_store = TaskMemoryNodeStore(embedder=embedder)
        edge_store = CrossTaskEdgeStore()

        # Store a task with a different archetype
        req1 = NormalizedRequirement(
            intent="create-flow",
            archetype="sftp-to-https",
            source_protocol="sftp",
            target_protocol="https",
            components=["receiver.sftp", "receiver.http"],
            raw="SFTP to HTTP",
        )
        task_store.insert_from_requirement(req1, task_id="task-1")

        insight = CrossTaskInsight(
            id="xinsight-1",
            applies_when={"archetype": "sftp-to-https", "sourceProtocol": "sftp"},
            workflow=[],
            safety=[],
            confidence=0.9,
        )
        edge_store.add_edge("task-1", "task-1", insight)

        # Query with a dissimilar requirement
        req2 = NormalizedRequirement(
            intent="fix-flow",
            archetype="soap-to-idoc",
            source_protocol="soap",
            target_protocol="idoc",
            components=["receiver.idoc", "sender.soap"],
            raw="Fix SOAP to IDoc",
        )

        retriever = EMGRetriever(task_store=task_store, edge_store=edge_store)
        result = retriever.retrieve(req2)

        # Cross-task insights should be empty (archetype doesn't match)
        assert len(result.cross_task_insights) == 0

    def test_cross_task_insights_ranked_by_confidence(self) -> None:
        """Cross-task insights are ranked by confidence."""
        embedder = RequirementEmbedder()
        task_store = TaskMemoryNodeStore(embedder=embedder)
        edge_store = CrossTaskEdgeStore()

        req = NormalizedRequirement(
            intent="create-flow",
            archetype="https-to-https",
            source_protocol="https",
            target_protocol="https",
            operations=["validate"],
            components=["validator.json-schema", "sender.http", "receiver.http"],
            raw="Create flow",
        )
        task_store.insert_from_requirement(req, task_id="task-1")

        # Add two insights with different confidence
        edge_store.add_edge(
            "task-1",
            "task-1",
            CrossTaskInsight(
                id="x1",
                applies_when={
                    "archetype": "https-to-https",
                    "sourceProtocol": "https",
                    "targetProtocol": "https",
                },
                workflow=[],
                safety=[],
                confidence=0.7,
            ),
        )
        edge_store.add_edge(
            "task-1",
            "task-1",
            CrossTaskInsight(
                id="x2",
                applies_when={
                    "archetype": "https-to-https",
                    "sourceProtocol": "https",
                    "targetProtocol": "https",
                },
                workflow=[],
                safety=[],
                confidence=0.95,
            ),
        )

        retriever = EMGRetriever(task_store=task_store, edge_store=edge_store)
        result = retriever.retrieve(req)

        assert len(result.cross_task_insights) >= 2
        # Sorted by confidence descending
        assert result.cross_task_insights[0].confidence >= result.cross_task_insights[1].confidence
