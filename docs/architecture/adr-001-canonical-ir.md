# ADR-001: Canonical IR rather than archive-as-source

- Status: ADOPTED
- Date: 2026-07-31
- Spec ref: §4.1, §4.2, §7

## Context

SAP Cloud Integration content is normally authored in a tenant browser UI and
stored as opaque XML + binary packages. This makes Git-based workflows,
semantic code review, deterministic builds, and LLM-assisted authoring
effectively impossible.

## Decision

Adopt a canonical, human-readable Intermediate Representation (IR) as the
single authoring surface. All authoring tools (CLI, UI, LLM tools) operate
exclusively on the IR. SAP import/export is a compiler boundary — no
proprietary structures leak into the authoring layer.

The IR is:
- Versioned (`apiVersion: oiw.dev/v1alpha1`)
- Schema-validated (JSON Schema)
- Git-friendly (YAML + text resources)
- Deterministic (canonical ordering, sorted keys)
- Lossless (unknown imported data preserved in `extensions` blocks)

## Consequences

- Positive: Git is the source of truth; semantic diffs work; LLMs can read and edit safely.
- Positive: SAP format changes do not break authoring — only the compiler needs updating.
- Negative: Round-trips may not be lossless; every import produces a report (spec §8.3).
