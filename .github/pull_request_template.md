## Summary

<!-- What does this PR change and why? -->

## Spec ref

<!-- Which section of the spec does this address? e.g. §14.1, §9.4 -->

## Change log

<!-- Bullet list of concrete changes -->

## Validation

- [ ] `oiw validate --strict --project examples/order-to-s4` passes
- [ ] `oiw test --all --project examples/order-to-s4` passes
- [ ] `oiw build --project examples/order-to-s4 --target sap-cloud-integration-2026-07` produces a deterministic digest
- [ ] `pytest apps/cli/tests/ -v` passes
- [ ] `ruff check apps/cli/` passes
- [ ] `ruff format --check apps/cli/` passes
- [ ] CI is green

## Definition of Done (spec §22)

- [ ] Tests added or updated
- [ ] Threat impact considered
- [ ] No secrets in fixtures
- [ ] Public API documented
- [ ] Schema changes versioned
- [ ] Migration included when needed
- [ ] Compatibility diagnostics updated
- [ ] UI and CLI remain consistent
- [ ] SBOM and scans pass
- [ ] ADR added for significant architectural change
- [ ] `DEVELOPMENT_LOG.md` updated with a new entry

## AI provenance (if AI-assisted)

```
AI-Model:
AI-Provider:
AI-Tool-Calls:
Human-Approver:
```
