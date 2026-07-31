# ADR-006: Git as source of truth

- Status: ADOPTED
- Date: 2026-07-31
- Spec ref: §4.1, §11

## Context

SAP Cloud Integration content normally lives in a proprietary tenant. Git
history, branching, code review, and CI are not first-class.

## Decision

Treat the Git repository as the source of truth. The project is stored as
normalized text and resources (IR + scripts + schemas + tests). Generated
SAP-compatible packages are build outputs in `dist/` (gitignored). The
`.oiw/compiler.lock` records the last build's compiler version and digest
(spec §11.4) so drift can be detected.

## Consequences

- Positive: Pull requests, semantic diffs, code review, CI all work natively.
- Positive: History is auditable; reverting is meaningful.
- Positive: Deterministic builds (spec §4.7) make "same revision → same bytes" enforceable.
- Negative: Tenant becomes a deployment target, not a source; drift detection (spec §15.3) is required.
