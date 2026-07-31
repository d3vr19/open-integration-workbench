"""Semantic diff engine.

Spec ref: §10.5 (Semantic Diff), §11.5 (Merge Conflict Resolution).

Produces a human-readable summary of changes between two project revisions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def semantic_diff(project_root: Path, rev: str = "HEAD~1") -> str:
    """Show what changed between `rev` and HEAD, expressed in IR terms."""
    project_root = project_root.resolve()

    # Get list of changed files via git
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "diff", "--name-status", rev, "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        return f"error: git diff failed: {exc.stderr or exc}"
    except FileNotFoundError:
        return "error: git not available"

    changes = _parse_name_status(result.stdout)
    if not changes:
        return "no changes"

    head_sha = _git_sha(project_root, "HEAD")
    base_sha = _git_sha(project_root, rev)

    lines = [f"Project diff: {base_sha} → {head_sha}", ""]

    added_flows = []
    modified_flows = []
    removed_flows = []
    added_resources = []
    modified_resources = []
    removed_resources = []
    added_tests = []
    modified_tests = []
    removed_tests = []
    other = []

    for status, path in changes:
        if path.startswith("flows/") and path.endswith("flow.yaml"):
            if status == "A":
                added_flows.append(path)
            elif status == "D":
                removed_flows.append(path)
            else:
                modified_flows.append(path)
        elif path.startswith("flows/") and "/resources/" in path:
            if status == "A":
                added_resources.append(path)
            elif status == "D":
                removed_resources.append(path)
            else:
                modified_resources.append(path)
        elif path.startswith("flows/") and "/tests/" in path and path.endswith(".yaml"):
            if status == "A":
                added_tests.append(path)
            elif status == "D":
                removed_tests.append(path)
            else:
                modified_tests.append(path)
        else:
            other.append((status, path))

    if added_flows:
        lines.append("Added flows:")
        for p in added_flows:
            lines.append(f"  + {p}")
    if modified_flows:
        lines.append("Modified flows:")
        for p in modified_flows:
            lines.append(f"  ~ {p}")
    if removed_flows:
        lines.append("Removed flows:")
        for p in removed_flows:
            lines.append(f"  - {p}")

    if added_resources:
        lines.append("Added resources:")
        for p in added_resources:
            lines.append(f"  + {p}")
    if modified_resources:
        lines.append("Modified resources:")
        for p in modified_resources:
            lines.append(f"  ~ {p}")
    if removed_resources:
        lines.append("Removed resources:")
        for p in removed_resources:
            lines.append(f"  - {p}")

    if added_tests:
        lines.append("Added tests:")
        for p in added_tests:
            lines.append(f"  + {p}")
    if modified_tests:
        lines.append("Modified tests:")
        for p in modified_tests:
            lines.append(f"  ~ {p}")
    if removed_tests:
        lines.append("Removed tests:")
        for p in removed_tests:
            lines.append(f"  - {p}")

    if other:
        lines.append("Other changes:")
        for status, p in other:
            sym = {"A": "+", "M": "~", "D": "-", "R": "R"}.get(status, "?")
            lines.append(f"  {sym} {p}")

    # Summary footer — would be populated by running validation + tests
    lines.append("")
    lines.append("Run `oiw validate --strict` and `oiw test --all` for full review.")
    return "\n".join(lines)


def _parse_name_status(stdout: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) == 2:
            out.append((parts[0].strip(), parts[1].strip()))
        elif len(parts) >= 3:
            # Renames: R100\told\tnew
            out.append((parts[0].strip(), parts[-1].strip()))
    return out


def _git_sha(root: Path, rev: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", rev],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return rev
