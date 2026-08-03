# WSL2 bootstrap

Spec ref: §18.3 (Windows WSL2 Bootstrap).

## Quick start (PowerShell on Windows)

```powershell
# 1. Install WSL2 + Ubuntu 24.04 (one-time)
wsl --install -d Ubuntu-24.04

# 2. Run the OIW bootstrap inside WSL
wsl -d Ubuntu-24.04 -- bash -c "$(curl -fsSL https://raw.githubusercontent.com/hehenaice/open-integration-workbench/main/deploy/wsl/bootstrap.sh)"
```

This installs Python 3.12 + git, clones the repo to `~/oiw`, installs the
`oiw` CLI, regenerates the golden + negative fixtures, and runs the
validation gate (`oiw validate`, `oiw test --all`, `oiw build`) on both
reference scenarios.

## Manual bootstrap (after cloning the repo on Windows)

```powershell
wsl -d Ubuntu-24.04 -- bash -c "cd /mnt/c/path/to/open-integration-workbench && bash deploy/wsl/bootstrap.sh"
```

## What the script does

1. Installs system dependencies: `python3`, `python3-pip`, `git`, `libxml2`, `libxslt1.1`, `build-essential`, `ca-certificates`, `curl`.
2. Clones the repo to `~/oiw` (or updates an existing clone).
3. Installs the `oiw` CLI in editable mode (`pip install --user -e apps/cli`).
4. Adds `~/.local/bin` to `PATH` (idempotent).
5. Regenerates all fixtures (golden + negative + soap-groovy-sftp).
6. Runs `oiw validate --strict`, `oiw test --all`, `oiw build` on both reference scenarios.
7. Prints next-steps.

## Environment overrides

| Variable | Default | Purpose |
|----------|---------|---------|
| `OIW_REPO_URL` | `https://github.com/hehenaice/open-integration-workbench.git` | Repo to clone |
| `OIW_HOME` | `$HOME/oiw` | Local clone path |
| `OIW_BRANCH` | `main` | Branch to checkout |

Example:

```bash
OIW_BRANCH=feature/phase-1-complete-mvp-steps bash deploy/wsl/bootstrap.sh
```

## Troubleshooting

- **`python3` not found**: install with `sudo apt-get install -y python3 python3-pip`.
- **`oiw` command not found after install**: run `source ~/.bashrc` or open a new shell.
- **`pip` warnings about `--break-system-packages`**: the script uses `--user` install which is allowed under PEP 668.
- **Docker not available**: Docker Desktop for Windows integrates with WSL2 automatically; install it from <https://docker.com> if missing.

## Phase 1 exit criterion

This script satisfies the Phase 1 exit criterion "Windows WSL2 setup is documented" (spec §19 Phase 1).
