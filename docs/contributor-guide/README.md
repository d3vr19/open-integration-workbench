# Contributor Guide

Welcome to Open Integration Workbench. This guide tells you how to make changes
safely. Read it once before your first PR.

## 1. Read the source of truth first

Before doing anything, read [`/DEVELOPMENT_LOG.md`](../../DEVELOPMENT_LOG.md).
It records:

- The current phase and what's implemented
- Active deviations from the spec
- Open work items
- The change log (newest at the bottom)

If your change is architectural, add an ADR under `docs/architecture/`.

## 2. Set up your environment

```bash
git clone https://github.com/hehenaice/open-integration-workbench.git
cd open-integration-workbench
pip install -e apps/cli[dev]
```

Verify the reference scenario passes:

```bash
oiw validate --strict --project examples/order-to-s4
oiw test --all --project examples/order-to-s4
oiw build --project examples/order-to-s4 --target sap-cloud-integration-2026-07
```

## 3. Make your change

- Follow the spec. The spec lives in the project root as the canonical source.
- Every new step plugin MUST declare a fidelity level (spec §4.3).
- Every new compatibility claim MUST have a fixture and a test (spec §8.5, §22 DoD).
- Every PR MUST add or update tests.
- Every significant architectural change MUST add an ADR.
- Never commit secrets. `gitleaks` runs in CI; violations block merge.
- Never commit customer artifacts. Fixtures MUST be synthetic or derived from
  publicly-available SAP samples.

## 4. Commit message convention (spec §11.3)

```
<type>(<scope>): <description>

Types: feat, fix, refactor, test, docs, chore, security, perf
Scope: flow, mapping, script, adapter, package, config, emg, compiler, ui
```

AI-generated commits include provenance trailers:

```
AI-Model: <model>
AI-Provider: <provider>
AI-Tool-Calls: <tools>
Human-Approver: <filled on merge>
```

Never store hidden model reasoning. Store task, patches, tool results, validation
results, and approvals only.

## 5. Before opening a PR

Run locally:

```bash
ruff check apps/cli/
ruff format --check apps/cli/
pytest apps/cli/tests/ -v
oiw validate --strict --project examples/order-to-s4
oiw test --all --project examples/order-to-s4
oiw build --project examples/order-to-s4 --target sap-cloud-integration-2026-07
```

The same checks run in CI (`.github/workflows/validate-on-pr.yaml`). CI is
authoritative — local hooks are optional.

## 6. Definition of Done (spec §22)

A PR is mergeable only when ALL of:

- [ ] Tests added or updated.
- [ ] Threat impact considered.
- [ ] No secrets in fixtures.
- [ ] Public API documented.
- [ ] Schema changes versioned.
- [ ] Migration included when needed.
- [ ] Compatibility diagnostics updated.
- [ ] UI and CLI remain consistent.
- [ ] SBOM and scans pass.
- [ ] ADR added for significant architectural change.
- [ ] `DEVELOPMENT_LOG.md` updated with what changed and why.

## 7. Update DEVELOPMENT_LOG.md

Append a new entry to the Change Log section. Format:

```
### YYYY-MM-DD — <your name / agent> — <summary>
- Change 1
- Change 2
- Files touched: <paths>
- Tests: <pass/fail summary>
- CI: <workflow run link>
```

Never rewrite history. Mark entries as superseded with a strikethrough note if needed.
