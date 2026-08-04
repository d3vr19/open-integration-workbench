"""Tests for EMG Phase C: embedding + task memory store (WP-06 Track C).

Covers:
  - Embed two similar requirements → cosine similarity > 0.5
  - Embed two dissimilar requirements → cosine similarity < 0.3
  - Embedding is deterministic for same input
  - Task store: insert + search_similar finds matching node
  - Task store: search returns not-found for novel requirement
  - Task store: list_approved filters correctly
"""

from __future__ import annotations

from oiw.agent.interpreter import NormalizedRequirement
from oiw.emg.embedding import RequirementEmbedder
from oiw.emg.task_store import TaskMemoryNode, TaskMemoryNodeStore


def _make_req(**kwargs) -> NormalizedRequirement:
    defaults = {
        "intent": "create-flow",
        "raw": "test",
    }
    defaults.update(kwargs)
    return NormalizedRequirement(**defaults)


class TestRequirementEmbedder:
    def test_similar_requirements_high_similarity(self) -> None:
        """Two similar requirements → cosine similarity > 0.5."""
        embedder = RequirementEmbedder()
        req1 = _make_req(
            intent="create-flow",
            archetype="https-to-https",
            source_protocol="https",
            target_protocol="https",
            operations=["validate", "transform"],
            components=["validator.json-schema", "receiver.http", "sender.http"],
        )
        req2 = _make_req(
            intent="create-flow",
            archetype="https-to-https",
            source_protocol="https",
            target_protocol="https",
            operations=["validate", "transform"],
            components=["validator.json-schema", "receiver.http", "sender.http"],
        )
        emb1 = embedder.embed(req1)
        emb2 = embedder.embed(req2)
        sim = emb1.cosine_similarity(emb2)
        assert sim > 0.5, f"expected > 0.5, got {sim}"

    def test_dissimilar_requirements_low_similarity(self) -> None:
        """Two dissimilar requirements → cosine similarity < 0.3."""
        embedder = RequirementEmbedder()
        req1 = _make_req(
            intent="create-flow",
            source_protocol="https",
            target_protocol="sftp",
            operations=["validate"],
            components=["validator.json-schema", "sender.http", "receiver.sftp"],
        )
        req2 = _make_req(
            intent="fix-flow",
            source_protocol="soap",
            target_protocol="idoc",
            operations=["route"],
            components=["receiver.idoc", "sender.soap", "router"],
        )
        emb1 = embedder.embed(req1)
        emb2 = embedder.embed(req2)
        sim = emb1.cosine_similarity(emb2)
        assert sim < 0.5, f"expected < 0.5, got {sim}"

    def test_embedding_deterministic(self) -> None:
        """Same requirement → same embedding."""
        embedder = RequirementEmbedder()
        req = _make_req(
            intent="create-flow",
            operations=["validate"],
            components=["validator.json-schema"],
        )
        emb1 = embedder.embed(req)
        emb2 = embedder.embed(req)
        assert emb1.vector == emb2.vector
        assert emb1.requirement_hash == emb2.requirement_hash

    def test_embedding_handles_missing_fields(self) -> None:
        """Embedding handles missing fields gracefully."""
        embedder = RequirementEmbedder()
        req = _make_req(intent="general")
        emb = embedder.embed(req)
        assert len(emb.vector) > 0
        assert emb.text


class TestTaskMemoryNodeStore:
    def test_insert_and_get(self) -> None:
        """Insert a node and retrieve it by ID."""
        store = TaskMemoryNodeStore()
        node = TaskMemoryNode(
            id="test-1",
            task_id="task-1",
            requirement_embedding=[1.0, 0.0, 0.0],
            normalized_requirement={"intent": "create-flow"},
            approval="PROJECT_APPROVED",
        )
        store.insert(node)
        retrieved = store.get("test-1")
        assert retrieved is not None
        assert retrieved.task_id == "task-1"

    def test_insert_from_requirement(self) -> None:
        """insert_from_requirement creates a node with embedding."""
        store = TaskMemoryNodeStore()
        req = _make_req(
            intent="create-flow",
            operations=["validate"],
            components=["validator.json-schema"],
        )
        node = store.insert_from_requirement(req, task_id="task-1", project_id="proj-1")
        assert node.id.startswith("task-mem-")
        assert len(node.requirement_embedding) > 0
        assert node.approval == "PROJECT_APPROVED"

    def test_search_similar_finds_match(self) -> None:
        """search_similar finds a matching node for a similar requirement."""
        store = TaskMemoryNodeStore()
        req = _make_req(
            intent="create-flow",
            source_protocol="https",
            target_protocol="https",
            operations=["validate", "transform"],
            components=["validator.json-schema", "receiver.http", "sender.http"],
        )
        store.insert_from_requirement(req, task_id="task-1", project_id="proj-1")

        # Search with the same requirement
        results = store.search_similar_requirement(req, project_id="proj-1")
        assert len(results) > 0
        assert results[0][0].task_id == "task-1"
        assert results[0][1] > 0.5  # high similarity

    def test_search_returns_empty_for_novel(self) -> None:
        """search_similar returns empty for a novel (dissimilar) requirement."""
        store = TaskMemoryNodeStore()
        req1 = _make_req(
            intent="create-flow",
            source_protocol="https",
            target_protocol="https",
            components=["validator.json-schema", "receiver.http"],
        )
        store.insert_from_requirement(req1, task_id="task-1")

        req2 = _make_req(
            intent="fix-flow",
            source_protocol="idoc",
            target_protocol="smtp",
            components=["receiver.idoc", "receiver.mail"],
        )
        results = store.search_similar_requirement(req2, min_similarity=0.8)
        assert len(results) == 0

    def test_list_approved(self) -> None:
        """list_approved returns only approved nodes."""
        store = TaskMemoryNodeStore()
        store.insert(
            TaskMemoryNode(
                id="n1",
                task_id="t1",
                requirement_embedding=[1.0],
                normalized_requirement={},
                approval="PROJECT_APPROVED",
            )
        )
        store.insert(
            TaskMemoryNode(
                id="n2",
                task_id="t2",
                requirement_embedding=[1.0],
                normalized_requirement={},
                approval="CAPTURED",
            )
        )
        approved = store.list_approved()
        assert len(approved) == 1
        assert approved[0].id == "n1"

    def test_count(self) -> None:
        """count returns total node count."""
        store = TaskMemoryNodeStore()
        assert store.count() == 0
        store.insert(
            TaskMemoryNode(
                id="n1",
                task_id="t1",
                requirement_embedding=[1.0],
                normalized_requirement={},
            )
        )
        assert store.count() == 1
