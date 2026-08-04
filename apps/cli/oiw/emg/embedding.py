"""Requirement embedding for cross-task similarity search (WP-06 Task C-001).

Spec ref: §15.11 (Retrieval), §15.13 (Cross-Task Transfer).

Embeds normalized requirements into vectors for similarity search.
Uses TF-IDF as the default embedding method (no external dependencies).
A sentence-transformers backend can be plugged in later for better
semantic matching.

The embedding enables the EMG to find similar tasks across different
flows/projects — the core of cross-task transfer (Phase C).
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass

from ..agent.interpreter import NormalizedRequirement


@dataclass
class RequirementEmbedding:
    """An embedded requirement vector + metadata."""

    vector: list[float]
    text: str
    requirement_hash: str

    def cosine_similarity(self, other: RequirementEmbedding) -> float:
        """Compute cosine similarity between two embeddings."""
        if len(self.vector) != len(other.vector):
            return 0.0
        dot = sum(a * b for a, b in zip(self.vector, other.vector, strict=True))
        mag_a = math.sqrt(sum(a * a for a in self.vector))
        mag_b = math.sqrt(sum(b * b for b in other.vector))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)


class RequirementEmbedder:
    """Embed normalized requirements into vectors for similarity search.

    Uses TF-IDF over the requirement's structured fields (intent,
    archetype, protocols, operations, components). This is deterministic,
    fast, and requires no external dependencies.

    A sentence-transformers backend can replace this later — the
    RequirementEmbedding interface stays the same.
    """

    # Vocabulary built from known OIW terms. Each term maps to a dimension.
    VOCABULARY: list[str] = [
        # Intents
        "create-flow",
        "modify-flow",
        "fix-flow",
        "add-test",
        "refactor",
        # Archetypes
        "api-to-erp",
        "file-to-api",
        "api-to-api",
        "erp-to-api",
        "https-to-https",
        "https-to-sftp",
        "sftp-to-https",
        "sftp-to-sftp",
        "https-to-soap",
        "soap-to-https",
        "https-to-odata",
        # Protocols
        "https",
        "sftp",
        "soap",
        "odata",
        "idoc",
        "smtp",
        "timer",
        "jdbc",
        # Operations
        "validate",
        "transform",
        "route",
        "filter",
        "split",
        "gather",
        "encode",
        "log",
        # Components
        "validator.json-schema",
        "script.groovy",
        "transform.xslt",
        "receiver.http",
        "receiver.sftp",
        "receiver.soap",
        "receiver.odata-v4",
        "receiver.idoc",
        "receiver.mail",
        "sender.http",
        "sender.sftp",
        "sender.soap",
        "modifier.content",
        "router",
        "filter",
        "splitter",
        "gather",
        "encoder.base64",
        "log.message",
        "converter.json-to-xml",
        "converter.xml-to-json",
    ]

    # Build term-to-index mapping
    TERM_INDEX: dict[str, int] = {term: i for i, term in enumerate(VOCABULARY)}

    def __init__(self) -> None:
        self._vocab_size = len(self.VOCABULARY)
        # Document frequency for IDF (pre-computed from OIW domain knowledge)
        self._df = {term: 1 for term in self.VOCABULARY}  # uniform DF = 1
        self._total_docs = len(self.VOCABULARY)

    def embed(self, requirement: NormalizedRequirement) -> RequirementEmbedding:
        """Embed a normalized requirement into a vector.

        Args:
            requirement: The normalized requirement to embed.

        Returns:
            RequirementEmbedding with the TF-IDF vector + text representation.
        """
        text = self._requirement_to_text(requirement)
        terms = self._extract_terms(requirement)

        # TF: count term occurrences
        tf = Counter(terms)

        # TF-IDF vector
        vector = [0.0] * self._vocab_size
        for term, count in tf.items():
            if term in self.TERM_INDEX:
                idx = self.TERM_INDEX[term]
                idf = math.log(self._total_docs / self._df.get(term, 1))
                vector[idx] = count * idf

        # Normalize
        magnitude = math.sqrt(sum(v * v for v in vector))
        if magnitude > 0:
            vector = [v / magnitude for v in vector]

        req_hash = hashlib.sha256(text.encode()).hexdigest()[:16]

        return RequirementEmbedding(
            vector=vector,
            text=text,
            requirement_hash=req_hash,
        )

    def _requirement_to_text(self, req: NormalizedRequirement) -> str:
        """Convert normalized requirement to embeddable text."""
        parts = [
            f"intent: {req.intent}",
            f"archetype: {req.archetype or 'unknown'}",
            f"source: {req.source_protocol or 'unknown'}",
            f"target: {req.target_protocol or 'unknown'}",
            f"operations: {', '.join(req.operations)}",
            f"components: {', '.join(req.components)}",
        ]
        return " | ".join(parts)

    def _extract_terms(self, req: NormalizedRequirement) -> list[str]:
        """Extract vocabulary terms from a requirement."""
        terms: list[str] = []

        # Intent
        if req.intent:
            terms.append(req.intent)

        # Archetype
        if req.archetype:
            terms.append(req.archetype)

        # Protocols
        if req.source_protocol:
            terms.append(req.source_protocol)
        if req.target_protocol:
            terms.append(req.target_protocol)

        # Operations
        terms.extend(req.operations)

        # Components
        terms.extend(req.components)

        return terms


__all__ = ["RequirementEmbedder", "RequirementEmbedding"]
