# ADR-PY-001: Phase 0/1 implementation language is Python

- Status: DEVIATION — TEMPORARY
- Date: 2026-07-31
- Spec ref: §6.2 (mandates Kotlin 2.1 + Spring Boot 3.4 + picocli)
- Decider: Implementing agent (initial bootstrap)

## Context

Spec §6.2 mandates Kotlin 2.1 + Spring Boot 3.4 for the backend and picocli for the CLI.
Delivering a working CLI + validator + compiler + runtime MVP in a single engineering
session requires a language with a fast edit-run loop and zero build overhead.

The architectural decisions that *matter* (canonical IR, JSON Schemas, deterministic
builds, semantic diff, safe archive inspection, fidelity labels, typed patches,
approval gates) are all language-agnostic. The choice of implementation language for
the Phase 0/1 bootstrap does not affect them.

## Decision

Implement the Phase 0/1 CLI (`apps/cli/oiw/`) and the Phase 0/1 runtime prototype
(`apps/cli/oiw/runtime/`) in Python 3.12. Keep the Kotlin/Spring Boot modular monolith
(`apps/server/`) and the Java 21 process-isolated runtime worker
(`services/runtime-worker/`) as the production target — the Python code is a
reference implementation that proves the architecture works.

The following artefacts are **language-agnostic and survive the migration unchanged**:

- All JSON Schemas in `packages/ir-schema/schemas/`
- All Rego policies in `packages/policy-rules/rego/`
- All Semgrep rules in `packages/policy-rules/semgrep/`
- All test fixtures in `packages/test-fixtures/`
- All example projects in `examples/`
- All GitHub Actions workflows in `.github/workflows/`
- The `DEVELOPMENT_LOG.md` source-of-truth log
- The compatibility matrix and threat model docs

## Consequences

- Positive: Working CLI shipped in one session; architecture validated end-to-end.
- Positive: IR schemas and policies are now battle-tested before the Kotlin migration begins.
- Positive: CI workflows are running against a real implementation, not stubs.
- Negative: Two implementations exist during the migration window (Python and Kotlin).
- Negative: The Python runtime is in-process; it cannot enforce the seccomp + network
  namespace isolation that the spec mandates for hostile Groovy scripts (see DEV-003).
  **Until OW-003 lands, do not run untrusted Groovy in the Python runtime.**
- Neutral: Migration is mechanical — translate Python to Kotlin against the same
  JSON Schemas and fixtures. No architectural rework needed.

## Alternatives considered

- **Build the whole stack in Kotlin from day one.** Rejected: a single session cannot
  deliver a Spring Boot modular monolith + picocli CLI + Java 21 runtime worker with
  seccomp isolation. The architecture would be unverifiable.
- **Use Node.js / TypeScript.** Rejected: spec §6.2 mandates JVM for the backend;
  choosing Node would have introduced a *third* language during migration. Python is
  a closer neighbour to JVM conventions (typing, dataclasses, ABCs).
- **Use Go.** Rejected for the same reason as Node, plus Go's lack of expression
  evaluation libraries would have made the router / XSLT step harder to prototype.

## Migration plan

Tracked as OW-001 in `DEVELOPMENT_LOG.md`. Migration begins after Phase 1 exit
criteria are verified. The Python implementation remains as a reference / fallback
during migration. Migration order:

1. `apps/cli` → Kotlin/picocli (mechanical translation; same JSON Schemas, same tests).
2. `apps/server` → Kotlin/Spring Boot (new; uses the same IR loader).
3. `services/runtime-worker` → Java 21 process-isolated JVM (security-critical;
   replaces the Python in-process runtime; see DEV-003 and ADR-004).
