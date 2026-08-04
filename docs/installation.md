# OIW Installation Guide

> WP-06 Track G Task G-001. Spec ref: §31 (Documentation).

## Prerequisites

- **Docker 24+** and Docker Compose v2 ([install](https://docs.docker.com/get-docker/))
- **Git 2.40+** ([install](https://git-scm.com/downloads))
- **Python 3.12+** (for CLI — [install](https://python.org))
- **Node 22+** (for web UI development — [install](https://nodejs.org))

## Quick Start (Linux / WSL2)

```bash
curl -fsSL https://raw.githubusercontent.com/hehenaice/open-integration-workbench/main/deploy/install-linux.sh | bash
```

Or clone and run manually:

```bash
git clone https://github.com/hehenaice/open-integration-workbench.git
cd open-integration-workbench
docker compose -f deploy/docker-compose/docker-compose.yaml --profile beta up -d --build
```

## Quick Start (Windows WSL2)

```powershell
# In PowerShell (Admin)
git clone https://github.com/hehenaice/open-integration-workbench.git
cd open-integration-workbench
.\deploy\wsl\install.ps1
```

## Access Points

| Service | URL | Description |
|---------|-----|-------------|
| Web UI | http://localhost:5173 | Visual workbench (flow canvas, co-pilot, deploy panel) |
| API | http://localhost:8000/docs | REST API with Swagger UI |
| CLI | `python -m oiw.cli --help` | Command-line interface |

## First Steps

1. **Open the Web UI** at http://localhost:5173
2. **Select a project** from the left sidebar (order-to-s4 or sftp-order-drop)
3. **Select a flow** to view the integration graph
4. **Try the Co-Pilot**: type a requirement like "Add JSON schema validation" and click Suggest
5. **Check EMG Insights**: the panel below the co-pilot shows preloaded patterns from the seed corpus (50 trajectories)
6. **Try the Deploy Panel**: select a profile (dev/test/prod), check drift, propose a deployment

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OIW_WORKSPACE` | `./examples` | Directory containing integration projects |
| `OIW_MODEL_GATEWAY_URL` | `http://127.0.0.1:8080` | Model gateway URL for LLM features |
| `OIW_MODEL_GATEWAY_KEY` | (none) | API key for the model gateway |
| `OIW_MAX_TOKENS_PER_DAY` | `2000000` | Per-project daily token budget |
| `DEV_TENANT_URL` | (env) | Dev tenant URL (for deployment profiles) |
| `DEV_CLIENT_ID` | (env) | Dev tenant OAuth2 client ID |
| `DEV_TOKEN_URL` | (env) | Dev tenant OAuth2 token URL |

### Environment Profiles

Create `environments/dev.yaml`, `environments/test.yaml`, `environments/prod.yaml` in your project:

```yaml
apiVersion: oiw.dev/v1alpha1
kind: EnvironmentProfile
metadata:
  name: dev
spec:
  target: sap-cloud-integration-2026-07
  tenantUrl: ${DEV_TENANT_URL}
  auth:
    method: oauth2-client-credentials
    tokenUrl: ${DEV_TOKEN_URL}
    clientId: ${DEV_CLIENT_ID}
    credentialRef: sap-dev-api-client
  deploymentPolicy:
    requiresApproval: false
    autoVerify: true
```

## CLI Usage

```bash
# Validate a project
oiw validate --strict --project examples/order-to-s4

# Run tests
oiw test --all --project examples/order-to-s4

# Build an artifact
oiw build --project examples/order-to-s4 --target sap-cloud-integration-2026-07

# Run the agent
oiw agent "Add JSON schema validation to order-to-s4"

# Deploy
oiw deploy --profile dev --package order-to-s4 --propose
oiw deploy --profile dev --package order-to-s4 --approve --approver alice
oiw deploy --profile dev --package order-to-s4 --upload
oiw deploy --profile dev --package order-to-s4 --execute
oiw deploy --profile dev --package order-to-s4 --verify

# View trajectories
oiw trajectory show --last

# Seed corpus
python -m packages.seed_corpus.populate_corpus
```

## Troubleshooting

### "Port 8000 already in use"

Another service is using port 8000. Stop it or change the port in `docker-compose.yaml`:
```yaml
ports:
  - "8001:8000"  # use 8001 externally
```

### "Docker permission denied"

Add your user to the docker group:
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### "Web UI shows blank page"

The web UI needs the API server running. Check:
```bash
docker compose -f deploy/docker-compose/docker-compose.yaml --profile beta ps
docker compose -f deploy/docker-compose/docker-compose.yaml --profile beta logs oiw-server-beta
```

### "EMG Insights panel shows 'No insights found'"

The seed corpus needs to be populated:
```bash
cd /path/to/open-integration-workbench
PYTHONPATH=apps/cli:packages/seed-corpus:. python -m populate_corpus
```

### "Co-pilot panel shows OIW-W014 warning"

This means the model gateway is not running. The co-pilot falls back to the keyword planner. To use the LLM:
1. Start the model gateway: `cd services/model-gateway-python && python -m oiw_gateway`
2. Set `OIW_MODEL_GATEWAY_KEY` env var with your API key

## Development Setup

For development without Docker:

```bash
# Install Python packages
pip install -e apps/cli
pip install -e apps/mcp-server
pip install -e apps/server-python-prototype
pip install -e services/model-gateway-python

# Install web dependencies
cd apps/web && npm install

# Start API server
cd apps/server-python-prototype
PYTHONPATH=../cli:../mcp-server:. python -m uvicorn oiw_server.main:app --reload

# Start web dev server (separate terminal)
cd apps/web
npm run dev

# Run tests
pytest apps/cli/tests/ -v
pytest apps/server-python-prototype/tests/ -v
pytest apps/mcp-server/tests/ -v
pytest packages/seed-corpus/ -v
```

## Uninstall

```bash
docker compose -f deploy/docker-compose/docker-compose.yaml --profile beta down -v
rm -rf ~/oiw
```
