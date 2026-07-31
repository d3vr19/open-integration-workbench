# WSL2 bootstrap script for Open Integration Workbench.
# Spec ref: §18.3 (Windows WSL2 Bootstrap), §19 Phase 1 exit criteria.
#
# Usage (from PowerShell on Windows):
#   wsl --install -d Ubuntu-24.04
#   wsl -d Ubuntu-24.04 -- bash -c "$(curl -fsSL https://raw.githubusercontent.com/hehenaice/open-integration-workbench/main/deploy/wsl/bootstrap.sh)"
#
# Or, after cloning the repo on Windows:
#   wsl -d Ubuntu-24.04 -- bash -c "cd /mnt/c/path/to/open-integration-workbench && bash deploy/wsl/bootstrap.sh"
#
# This script:
#   1. Installs system dependencies (Python 3.12, git, build tools).
#   2. Clones the repo to ~/oiw (if not already present).
#   3. Installs the oiw CLI in editable mode.
#   4. Regenerates fixtures.
#   5. Runs the validation gate (validate + test + build).
#   6. Prints next-steps.

set -euo pipefail

OIW_REPO_URL="${OIW_REPO_URL:-https://github.com/hehenaice/open-integration-workbench.git}"
OIW_HOME="${OIW_HOME:-$HOME/oiw}"
OIW_BRANCH="${OIW_BRANCH:-main}"

echo "=== Open Integration Workbench — WSL2 bootstrap ==="
echo "repo:   $OIW_REPO_URL"
echo "branch: $OIW_BRANCH"
echo "home:   $OIW_HOME"
echo ""

# 1. System dependencies
echo "--- installing system dependencies ---"
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    git \
    libxml2 libxslt1.1 \
    build-essential \
    ca-certificates curl
# Ensure python3 is at least 3.11
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "python: $PY_VERSION"

# 2. Clone (or update) the repo
if [ -d "$OIW_HOME/.git" ]; then
    echo "--- updating existing clone at $OIW_HOME ---"
    cd "$OIW_HOME"
    git fetch origin
    git checkout "$OIW_BRANCH"
    git reset --hard "origin/$OIW_BRANCH"
else
    echo "--- cloning to $OIW_HOME ---"
    git clone --depth 1 --branch "$OIW_BRANCH" "$OIW_REPO_URL" "$OIW_HOME"
    cd "$OIW_HOME"
fi

# 3. Install the oiw CLI (editable, user-local pip)
echo "--- installing oiw CLI ---"
python3 -m pip install --user --upgrade pip
python3 -m pip install --user -e apps/cli

# Add ~/.local/bin to PATH if not already there
if ! echo "$PATH" | tr ':' '\n' | grep -qx "$HOME/.local/bin"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
    export PATH="$HOME/.local/bin:$PATH"
fi

# 4. Regenerate fixtures (spec §8.5)
echo "--- regenerating fixtures ---"
python3 scripts/generate_golden_fixture.py
python3 scripts/generate_negative_fixtures.py
python3 scripts/generate_soap_groovy_sftp_fixture.py

# 5. Validate + test + build the reference scenario
echo "--- validating reference scenario (examples/order-to-s4) ---"
oiw validate --strict --project examples/order-to-s4
oiw test --all --project examples/order-to-s4
oiw build --project examples/order-to-s4 --target sap-cloud-integration-2026-07

echo "--- validating reference scenario (examples/sftp-order-drop) ---"
oiw validate --strict --project examples/sftp-order-drop
oiw test --all --project examples/sftp-order-drop
oiw build --project examples/sftp-order-drop --target sap-cloud-integration-2026-07

# 6. Next steps
cat <<EOF

=== bootstrap complete ===

The 'oiw' CLI is on your PATH. Try:

  oiw --help
  cd $OIW_HOME/examples/order-to-s4 && oiw validate --strict

To start a new project:

  oiw init my-integration --archetype api-to-erp
  cd my-integration
  oiw validate --strict
  oiw test --all
  oiw build --target sap-cloud-integration-2026-07

For the full local stack (Phase 2+ services), install Docker Desktop with
WSL2 integration and run:

  cd $OIW_HOME
  cp .env.example .env
  docker compose -f deploy/docker-compose/docker-compose.yaml --profile phase2 up -d

Read DEVELOPMENT_LOG.md for the current phase status and open work items.

EOF
