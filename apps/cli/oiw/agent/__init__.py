"""OIW agent pipeline — LLM-driven requirement interpretation, planning,
execution, and trajectory recording.

WP-04 (Work Package 4): LLM-Driven Agent Pipeline & Trajectory Instrumentation.

Modules:
  gateway_client  — async HTTP client for the model gateway (Task 5)
  redaction       — secret stripping for trajectory persistence (Task 4)
  normalization   — action/observation normalization (Task 4, spec §15.4/15.5)
  trajectory      — EngineeringTrajectory recorder + persistence (Task 4)
  interpreter     — LLM-driven requirement interpreter (Task 1)
  planner         — LLM-driven plan generator (Task 2)
  executor        — LLM-driven plan executor with bounded correction (Task 3)
  orchestrator    — top-level entry point: interpret → plan → execute (Task 7)

Fallback path: when the model gateway is unreachable, the orchestrator
falls back to the keyword-based interpreter/planner in
`apps/server-python-prototype/oiw_server/agent.py` and emits warning
OIW-W014.
"""

from __future__ import annotations

__version__ = "0.1.0"
