#!/usr/bin/env bash
set -euo pipefail

# OIW Installer for Linux / WSL2
# WP-06 Track F Task F-002

echo "=== OIW Installer ==="
echo "Open Integration Workbench"
echo ""

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker required. Install: https://docs.docker.com/get-docker/"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "ERROR: Git required."; exit 1; }
echo "✓ Docker and Git detected"

# Install directory
INSTALL_DIR="${OIW_INSTALL_DIR:-$HOME/oiw}"
if [ -d "$INSTALL_DIR" ]; then
    echo "OIW already installed at $INSTALL_DIR. Updating..."
    cd "$INSTALL_DIR"
    git pull --ff-only origin main
else
    echo "Cloning OIW to $INSTALL_DIR..."
    git clone https://github.com/hehenaice/open-integration-workbench.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Start with Docker Compose
echo ""
echo "Starting OIW (beta profile)..."
docker compose -f deploy/docker-compose/docker-compose.yaml --profile beta up -d --build

# Wait for services
echo "Waiting for services to start..."
sleep 5

# Check health
if curl -s http://localhost:8000/api/v1/health | grep -q "ok"; then
    echo "✓ API server is healthy at http://localhost:8000"
else
    echo "⚠ API server not responding yet. Check: docker compose logs oiw-server-beta"
fi

echo ""
echo "=== Installation Complete ==="
echo "  Web UI:  http://localhost:5173"
echo "  API:     http://localhost:8000/docs"
echo "  CLI:     cd $INSTALL_DIR && python -m oiw.cli --help"
echo ""
echo "To stop: docker compose -f deploy/docker-compose/docker-compose.yaml --profile beta down"
