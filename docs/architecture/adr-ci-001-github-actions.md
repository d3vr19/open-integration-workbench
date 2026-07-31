# ADR-CI-001: GitHub Actions are the validation gate

- Status: ADOPTED
- Date: 2026-07-31
- Spec ref: §14.4 (CI Pipeline), §11.6 (Git Hooks & Automation), §22 (Definition of Done)
- Decider: Implementing agent (initial bootstrap)

## Context

Spec §14.4 specifies a GitHub Actions pipeline that runs on every pull request:
schema validation, `oiw validate --strict`, `oiw test --all`, `oiw build`,
Semgrep, gitleaks, Trivy, SBOM generation, and (optionally) an LLM review.

Spec §11.6 specifies git hooks (pre-commit, pre-push, post-merge) but those are
local-only and easy to bypass. The CI gate is the authoritative check.

## Decision

Adopt GitHub Actions as the validation gate. Three workflows:

1. **`validate-on-pr.yaml`** — runs on every PR and push to main/develop.
   Jobs: `oiw-validate` (the core OIW gate), `schema-self-check`, `pytest`,
   `lint` (ruff), `log-check` (DEVELOPMENT_LOG.md must exist), and
   `validate-pr-aggregate` (required status check for branch protection).

2. **`security-scan.yaml`** — runs daily and on push to main.
   Jobs: Semgrep (with custom `cpi-rules.yml`), gitleaks, Trivy (HIGH/CRITICAL),
   SBOM (CycloneDX).

3. **`release.yaml`** — runs on tag push `v*.*.*`.
   Builds the reference scenario, packages the artifact, generates SBOM,
   attaches everything to a GitHub Release.

The aggregate job (`validate-pr-aggregate`) is the **single required status check**
for branch protection on `main`. This keeps the branch-protection config simple
(one check name) while still allowing individual jobs to fail loudly.

## Consequences

- Positive: Every PR is automatically validated against the spec's §14.1 rules
  and the §22 Definition of Done.
- Positive: Determinism is enforced in CI (the `oiw-validate` job re-builds and
  compares digests).
- Positive: Negative fixtures (zip-bomb, path-traversal, corrupt-manifest) are
  asserted to be rejected in CI.
- Negative: CI runtime is ~3-5 minutes per PR; acceptable for a Phase 0/1 project.
- Neutral: Local git hooks (pre-commit, pre-push) are documented but optional;
  CI is authoritative.

## Alternatives considered

- **GitLab CI.** Rejected: the project is hosted on GitHub; using a different
  CI provider would add friction without benefit.
- **Local hooks only.** Rejected: bypassable; spec §14.4 explicitly calls for CI.
- **Multiple required status checks.** Rejected: harder to maintain on
  branch-projection config; the aggregate job is simpler.
