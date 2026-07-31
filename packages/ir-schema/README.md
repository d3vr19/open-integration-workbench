# IR Schema Package

JSON Schemas for the Open Integration Workbench canonical Intermediate Representation.

## Schemas

| Schema | `$id` | Spec ref |
|--------|-------|----------|
| `oiw-project.json` | `https://schema.oiw.dev/project/v1alpha1.json` | §7.1 |
| `integration-flow.json` | `https://schema.oiw.dev/flow/v1alpha1.json` | §7.2 |
| `flow-test.json` | `https://schema.oiw.dev/flow-test/v1alpha1.json` | §7.4 |
| `environment-profile.json` | `https://schema.oiw.dev/environment-profile/v1alpha1.json` | §7.5 |

## Versioning

- All schemas carry `$id: https://schema.oiw.dev/<kind>/v1alpha1.json`.
- Schema changes are versioned per spec §22 Definition of Done: breaking changes bump the version (e.g. `v1beta1`); additive changes keep `v1alpha1` with a `since` note in the changelog below.
- The IR schema version is also recorded in `.oiw/compiler.lock` on every build (spec §11.4).

## Usage

The `oiw` CLI loads these schemas at startup and validates every project / flow / test / environment file against them on every `oiw validate` and `oiw test` invocation. Schema validation runs before any other rule-based validation (spec §14).

## Changelog

### v1alpha1 — 2026-07-31

- Initial schemas matching spec §7.1, §7.2, §7.4, §7.5.
- Fidelity levels match spec §4.3.
- Flow node `type` enum matches the MVP step coverage in spec §9.4.
- Lossless `extensions` block on `IntegrationFlow` per spec §7.3 rule 3.
- `generatedBy` provenance metadata on `IntegrationFlow.metadata` per spec §7.3 rule 8.
