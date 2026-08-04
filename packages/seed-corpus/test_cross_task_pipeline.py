"""Tests for cross-task pattern discovery pipeline (WP-07 Track C).

Covers:
  - C-001 Archetype clustering
  - C-002 Expert-to-expert matching within archetypes
  - C-003 Cross-task edge population (≥ 15 edges, ≥ 4 archetypes)
  - C-004 Retrieval verification
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cross_task_pipeline import (  # noqa: E402
    Artifact,
    classify_archetype,
    cluster_by_archetype,
    load_all_artifacts,
    populate_cross_task_edges,
    verify_cross_task_retrieval,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_ir(
    flow_id: str,
    sender_type: str = "sender.http",
    receiver_type: str = "receiver.http",
    extra_nodes: list[dict] | None = None,
    has_error_handling: bool = False,
) -> dict:
    nodes = [
        {"id": "sender", "type": sender_type, "config": {}},
        {"id": "receiver", "type": receiver_type, "config": {}},
    ]
    if extra_nodes:
        nodes = [nodes[0]] + extra_nodes + [nodes[1]]
    ir = {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationFlow",
        "metadata": {"id": flow_id, "name": flow_id, "version": 1, "labels": {}},
        "spec": {
            "entrypoints": [],
            "nodes": nodes,
            "edges": [],
            "extensions": {},
        },
    }
    if has_error_handling:
        ir["spec"]["errorHandling"] = {
            "defaultExceptionSubprocess": {
                "steps": [{"id": "log", "type": "log.message"}]
            }
        }
    return ir


# --------------------------------------------------------------------------- #
# C-001: Archetype classification + clustering
# --------------------------------------------------------------------------- #


class TestArchetypeClassification:
    def test_classify_http_to_http_no_transform(self) -> None:
        """HTTP→HTTP without transform → api-to-api."""
        ir = _make_ir("test", "sender.http", "receiver.http")
        assert classify_archetype(ir) == "api-to-api"

    def test_classify_http_to_http_with_transform(self) -> None:
        """HTTP→HTTP with transform → api-to-erp."""
        ir = _make_ir(
            "test",
            "sender.http",
            "receiver.http",
            extra_nodes=[{"id": "t", "type": "transform.xml-to-json", "config": {}}],
        )
        assert classify_archetype(ir) == "api-to-erp"

    def test_classify_sftp_to_http(self) -> None:
        """SFTP→HTTP → file-to-api."""
        ir = _make_ir("test", "sender.sftp", "receiver.http")
        assert classify_archetype(ir) == "file-to-api"

    def test_classify_http_to_sftp(self) -> None:
        """HTTP→SFTP → api-to-file."""
        ir = _make_ir("test", "sender.http", "receiver.sftp")
        assert classify_archetype(ir) == "api-to-file"

    def test_classify_soap(self) -> None:
        """SOAP sender → soap-integration."""
        ir = _make_ir("test", "sender.soap", "receiver.http")
        assert classify_archetype(ir) == "soap-integration"

    def test_classify_idoc(self) -> None:
        """IDoc receiver → idoc-integration."""
        ir = _make_ir("test", "sender.http", "receiver.idoc")
        assert classify_archetype(ir) == "idoc-integration"

    def test_classify_mail(self) -> None:
        """Mail receiver → mail-integration."""
        ir = _make_ir("test", "sender.http", "receiver.mail")
        assert classify_archetype(ir) == "mail-integration"

    def test_classify_paginated_odata(self) -> None:
        """HTTP→OData → paginated-api-ingestion."""
        ir = _make_ir("test", "sender.http", "receiver.odata-v4")
        assert classify_archetype(ir) == "paginated-api-ingestion"

    def test_classify_validation(self) -> None:
        """With validator → api-validation."""
        ir = _make_ir(
            "test",
            "sender.http",
            "receiver.http",
            extra_nodes=[{"id": "v", "type": "validator.json-schema", "config": {}}],
        )
        assert classify_archetype(ir) == "api-validation"

    def test_cluster_by_archetype(self) -> None:
        """Artifacts group by archetype."""
        arts = [
            Artifact(
                artifact_id="a1",
                source="synthetic",
                flow_id="f1",
                ir=_make_ir("f1", "sender.http", "receiver.http"),
                archetype="api-to-api",
            ),
            Artifact(
                artifact_id="a2",
                source="synthetic",
                flow_id="f2",
                ir=_make_ir("f2", "sender.http", "receiver.http"),
                archetype="api-to-api",
            ),
            Artifact(
                artifact_id="a3",
                source="synthetic",
                flow_id="f3",
                ir=_make_ir("f3", "sender.soap", "receiver.http"),
                archetype="soap-integration",
            ),
        ]
        clusters = cluster_by_archetype(arts)
        assert len(clusters["api-to-api"]) == 2
        assert len(clusters["soap-integration"]) == 1


# --------------------------------------------------------------------------- #
# C-002 + C-003: Cross-task edge population
# --------------------------------------------------------------------------- #


class TestCrossTaskEdgePopulation:
    def test_populate_edges_meets_acceptance(self, tmp_path: Path) -> None:
        """≥ 15 cross-task edges populated across ≥ 4 archetypes."""
        artifacts = load_all_artifacts(artifacts_dir=tmp_path / "artifacts")
        assert len(artifacts) >= 30  # sanity

        summary = populate_cross_task_edges(artifacts)

        # Acceptance: ≥ 15 edges (we add both directions, so 15 unique pairs → 30 edges)
        assert summary["totalEdges"] >= 15, f"only {summary['totalEdges']} edges"
        # Acceptance: ≥ 4 archetypes
        assert (
            summary["archetypesWithEdges"] >= 4
        ), f"only {summary['archetypesWithEdges']} archetypes with edges"

    def test_matches_were_run(self, tmp_path: Path) -> None:
        """The pipeline actually ran pair-wise matches."""
        artifacts = load_all_artifacts(artifacts_dir=tmp_path / "artifacts")
        summary = populate_cross_task_edges(artifacts)
        assert summary["matchesRun"] > 0
        assert summary["matchesKept"] > 0

    def test_edge_store_retrieval(self, tmp_path: Path) -> None:
        """CrossTaskEdgeStore returns edges for a known task."""
        artifacts = load_all_artifacts(artifacts_dir=tmp_path / "artifacts")
        summary = populate_cross_task_edges(artifacts)
        store = summary["edgeStore"]

        # Pick the first artifact and check it has edges
        from synthesize_trajectory import synthesize_expert_trajectory

        art = artifacts[0]
        art_dir = None
        # Find the artifact directory
        for candidate in [
            REPO_ROOT / "examples" / "order-to-s4" / "flows" / art.flow_id,
            REPO_ROOT / "examples" / "sftp-order-drop" / "flows" / art.flow_id,
            tmp_path / "artifacts" / art.artifact_id,
        ]:
            if candidate.is_dir():
                art_dir = candidate
                break
        assert art_dir is not None
        traj = synthesize_expert_trajectory(art_dir)
        task_id = traj.metadata.taskId or traj.metadata.id
        edges = store.get_edges_for_task(task_id, min_confidence=0.0)
        assert len(edges) > 0


# --------------------------------------------------------------------------- #
# C-004: Retrieval verification
# --------------------------------------------------------------------------- #


class TestCrossTaskRetrieval:
    def test_retrieval_returns_edges_for_sample(self, tmp_path: Path) -> None:
        """Cross-task retrieval returns relevant edges for ≥ 5 sample artifacts."""
        artifacts = load_all_artifacts(artifacts_dir=tmp_path / "artifacts")
        pop = populate_cross_task_edges(artifacts)
        verify = verify_cross_task_retrieval(pop["edgeStore"], artifacts, sample_size=5)

        assert verify["sampleSize"] == 5
        assert (
            verify["withEdges"] >= 5
        ), f"only {verify['withEdges']} of 5 samples had edges"
