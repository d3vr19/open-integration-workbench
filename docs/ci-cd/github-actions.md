# OIW CI/CD with GitHub Actions

WP-05 Task 5 / spec §18 (Tenant Connectivity).

This directory contains reusable GitHub Actions workflow templates for
OIW projects.

## Templates

### `oiw-validate.yaml`

Runs on every PR and push. Validates the project, runs tests, builds
the artifact, and uploads it as a GitHub artifact.

**Setup:** Copy to your project's `.github/workflows/` directory.

**Required secrets:** None (read-only workflow).

### `oiw-deploy.yaml`

Runs manually (workflow_dispatch). Deploys a package to a tenant
through the full pipeline: drift check → build → propose → approve →
upload → deploy → verify.

**Setup:**

1. Copy to your project's `.github/workflows/` directory.
2. Create GitHub Environments for each profile (dev, test, stage, prod):
   - Go to Settings → Environments → New environment
   - Add required reviewers for prod (deployment gate)
   - Add environment secrets (see below)
3. Set repository secrets:
   - `SAP_TENANT_URL` — tenant base URL (e.g. `https://mytenant.integrationsuite.cloud.sap`)
   - `SAP_TOKEN_URL` — OAuth2 token endpoint
   - `SAP_CLIENT_ID` — OAuth2 client ID
   - `SAP_CLIENT_SECRET` — OAuth2 client secret (set as environment secret, not repo secret)

**Required secrets per environment:**

| Secret | Description | Example |
|--------|-------------|---------|
| `SAP_TENANT_URL` | Tenant base URL | `https://mytenant.integrationsuite.cloud.sap` |
| `SAP_TOKEN_URL` | OAuth2 token endpoint | `https://mytenant.authentication.sap.hana.ondemand.com/oauth/token` |
| `SAP_CLIENT_ID` | OAuth2 client ID | `sb-myclient` |
| `SAP_CLIENT_SECRET` | OAuth2 client secret | (secret value) |

**Environment protection rules:**
- `dev`: no approval required (auto-deploy)
- `test`: 1 approver (QA lead)
- `stage`: 1 approver (integration lead)
- `prod`: 2 approvers (integration lead + ops lead)

## Usage

### Validate (automatic)

Every PR and push to `main` triggers `oiw-validate.yaml`. No manual
action needed.

### Deploy (manual)

1. Go to Actions → "OIW Deploy" → Run workflow
2. Select the environment profile (dev, test, stage, prod)
3. Enter the package ID (e.g., `order-to-s4`)
4. Click "Run workflow"

The workflow will:
1. Check for drift (block if tenant was modified externally)
2. Build the artifact
3. Propose a deployment (PROPOSED state)
4. Approve the deployment (APPROVED state) — the actor is the approver
5. Upload the artifact to the tenant (UPLOADED state)
6. Deploy the artifact (DEPLOYED state)
7. Run smoke tests (VERIFIED state)

If any step fails, the deployment transitions to FAILED state and the
state file is uploaded as an artifact for debugging.

## Environment Profiles

See `examples/order-to-s4/environments/` for sample profiles:
- `dev.yaml` — dev tenant, no approval required, auto-verify
- `test.yaml` — test tenant, approval required, 12h TTL
- `prod.yaml` — prod tenant, approval required

Profiles support `${ENV_VAR}` substitution so secrets are never stored
in the repository.

## Troubleshooting

### "environment variable 'DEV_TENANT_URL' is not set"

The profile references `${DEV_TENANT_URL}` but the env var isn't set.
Set it as a GitHub repository secret or environment secret.

### "DRIFT_DETECTED: tenant has been modified"

Someone modified the tenant directly (outside OIW). The upload is
blocked. Fetch the tenant artifact, review changes, and resolve
manually before re-running.

### "invalid deployment transition: DRAFT → DEPLOYED"

The deployment state machine enforces sequential transitions:
DRAFT → VALIDATED → TESTED → BUILT → PROPOSED → APPROVED →
UPLOADED → DEPLOYED → VERIFIED.

You can't skip states. Run the workflow in order.
