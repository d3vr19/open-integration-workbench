"""EMG subgraph extraction (WP-05 Tasks 11-12).

Spec ref: §15.9 (Common Subgraph + Edit Path).

Given a MatchResult (from exact + rule-based matching), extract:
  1. Common subgraph — actions already correct in the exploration
  2. Graph edit path — INSERT/DELETE/RELABEL/EDGE_CORRECTION operations
     needed to transform the exploration into the expert
"""

from __future__ import annotations

from .common import CommonEdge, CommonNode, CommonSubgraph, CommonSubgraphExtractor
from .edit_path import EditOperation, GraphEditPath, GraphEditPathExtractor

__all__ = [
    "CommonSubgraph",
    "CommonNode",
    "CommonEdge",
    "CommonSubgraphExtractor",
    "EditOperation",
    "GraphEditPath",
    "GraphEditPathExtractor",
]
