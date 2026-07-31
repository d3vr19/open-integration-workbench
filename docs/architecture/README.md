# Architecture Decision Records

This directory holds ADRs for Open Integration Workbench. Each ADR is a
short markdown file describing a single architectural decision.

## ADR index

| ADR | Decision | Status | Spec ref |
|-----|----------|--------|----------|
| [ADR-001](adr-001-canonical-ir.md) | Canonical IR rather than archive-as-source | ADOPTED | §4.1, §4.2, §7 |
| [ADR-002](adr-002-original-ui.md) | Original UI rather than SAP UI cloning | ADOPTED | §2.1, §2.2, §10.2 |
| [ADR-003](adr-003-modular-monolith.md) | Modular monolith first, extract later | ADOPTED | §4.8, §5.1 |
| [ADR-004](adr-004-jvm-runtime-worker.md) | JVM runtime worker for Groovy/XSLT | PLANNED | §9, §16.1 threat 2 |
| [ADR-005](adr-005-plugin-spi.md) | Plugin SPI for steps and adapters | PARTIAL | §9.3 |
| [ADR-006](adr-006-git-source-of-truth.md) | Git as source of truth | ADOPTED | §4.1, §11 |
| [ADR-007](adr-007-typed-agent-patches.md) | Typed agent patches (never raw file edits) | SPEC ACCEPTED | §12.1, §12.5 |
| [ADR-008](adr-008-approval-gated-deployment.md) | Approval-gated deployment | SPEC ACCEPTED | §4.4, §15.2 |
| [ADR-009](adr-009-emg-graph-matching.md) | EMG with graph matching rather than unstructured pattern bank | SPEC ACCEPTED | §13 |
| [ADR-010](adr-010-postgres-pgvector.md) | PostgreSQL/pgvector before dedicated graph DB | SPEC ACCEPTED | §13.16 |
| [ADR-011..020](adr-011-to-020.md) | Per-spec ADRs (edge-labelled graphs, edit paths, process isolation, deterministic builds, fidelity levels, Kotlin+Spring Boot, React Flow 12, MCP, 4-stage graph matching, negative knowledge) | SPEC ACCEPTED | §25 |
| [ADR-PY-001](adr-py-001-python-bootstrap.md) | Phase 0/1 implementation language is Python (DEVIATION) | DEVIATION — TEMPORARY | §6.2 |
| [ADR-PY-002](adr-py-002-fastapi-prototype.md) | Python FastAPI prototype for the REST API server (DEVIATION) | DEVIATION — TEMPORARY | §6.2, §21.1 |
| [ADR-PY-003](adr-py-003-mcp-server-prototype.md) | Python MCP server prototype (DEVIATION) | DEVIATION — TEMPORARY | §5.1, §12.4, §21.3 |
| [ADR-PY-004](adr-py-004-model-gateway-prototype.md) | Python model gateway prototype (DEVIATION) | DEVIATION — TEMPORARY | §5.1, §12.7 |
| [ADR-CI-001](adr-ci-001-github-actions.md) | GitHub Actions are the validation gate | ADOPTED | §14.4, §11.6 |

## ADR template

```markdown
# ADR-NNN: Title

- Status: PROPOSED | ADOPTED | DEPRECATED | SUPERSEDED by ADR-MMM
- Date: YYYY-MM-DD
- Spec ref: §X.Y
- Decider: <name / role>

## Context

Why is this decision needed? What problem are we solving?

## Decision

What did we decide?

## Consequences

- Positive: ...
- Negative: ...
- Neutral: ...

## Alternatives considered

- Alternative A: ...
  - Rejected because: ...
```

## How to add a new ADR

1. Copy the template above to `adr-NNN-<short-slug>.md` (use the next free number).
2. Fill in the context, decision, consequences, and alternatives.
3. Add a row to the index table above.
4. Reference the ADR from `DEVELOPMENT_LOG.md` if it changes the current phase plan.
