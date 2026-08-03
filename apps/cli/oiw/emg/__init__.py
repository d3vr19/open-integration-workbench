"""Experience Memory Graph (EMG) package (WP-05 Tasks 8-15).

Spec ref: §15.3-15.9 (EMG Phase B: Intra-Task Correction).

The EMG converts recorded EngineeringTrajectories into reusable
intra-task correction memory through:
  1. Action Decision Graph (ADG) construction (Task 8)
  2. Exact + rule-based graph matching (Tasks 9-10)
  3. Common subgraph + edit path extraction (Tasks 11-12)
  4. Insight compilation (Task 13)
  5. Memory promotion workflow (Task 14)
  6. Reward vector extension (Task 15)
"""

from __future__ import annotations

__version__ = "0.1.0"
