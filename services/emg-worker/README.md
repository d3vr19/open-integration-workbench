# `services/emg-worker` — Experience Memory Graph (Phase 5)

> **Status: NOT YET IMPLEMENTED (OW-006).**

When implemented, this Python 3.12 service will provide:

- Engineering trajectory recording (spec §13.3)
- Action and observation normalization (spec §13.5)
- Action decision graph construction (spec §13.4)
- Multidimensional reward scoring (spec §13.6)
- 4-stage graph matching: exact → rule-based → graph alignment → human (spec §13.7)
- Intra-task memory construction (spec §13.8)
- Cross-task memory edges (spec §13.9)
- Bounded retrieval packets (spec §13.10)
- Approval, revocation, invalidation workflow (spec §13.12)
- Tenant isolation and redaction pipeline (spec §13.15)

Storage: PostgreSQL + pgvector (spec §13.16, ADR-010).

Spec ref: §13 (Experience Memory Graph).
