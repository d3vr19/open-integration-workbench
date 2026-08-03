"""Semantic diff engine.

Spec ref: §10.5 (Semantic Diff), §11.5 (Merge Conflict Resolution).

Produces both human-readable and machine-readable (structured) diffs of
changes between two project revisions.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DiffEntry:
    """A single changed file in the diff."""

    path: str
    status: str  # "added" | "modified" | "removed" | "renamed"
    category: str  # "flow" | "resource" | "test" | "other"


@dataclass
class StructuredDiff:
    """Machine-readable semantic diff. Spec §10.5."""

    base_sha: str
    head_sha: str
    flows_added: list[str] = field(default_factory=list)
    flows_modified: list[str] = field(default_factory=list)
    flows_removed: list[str] = field(default_factory=list)
    resources_added: list[str] = field(default_factory=list)
    resources_modified: list[str] = field(default_factory=list)
    resources_removed: list[str] = field(default_factory=list)
    tests_added: list[str] = field(default_factory=list)
    tests_modified: list[str] = field(default_factory=list)
    tests_removed: list[str] = field(default_factory=list)
    other_changes: list[DiffEntry] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return (
            len(self.flows_added)
            + len(self.flows_modified)
            + len(self.flows_removed)
            + len(self.resources_added)
            + len(self.resources_modified)
            + len(self.resources_removed)
            + len(self.tests_added)
            + len(self.tests_modified)
            + len(self.tests_removed)
            + len(self.other_changes)
        )

    def to_dict(self) -> dict:
        return {
            "base_sha": self.base_sha,
            "head_sha": self.head_sha,
            "total_changes": self.total_changes,
            "flows": {
                "added": self.flows_added,
                "modified": self.flows_modified,
                "removed": self.flows_removed,
            },
            "resources": {
                "added": self.resources_added,
                "modified": self.resources_modified,
                "removed": self.resources_removed,
            },
            "tests": {
                "added": self.tests_added,
                "modified": self.tests_modified,
                "removed": self.tests_removed,
            },
            "other": [
                {"path": e.path, "status": e.status, "category": e.category} for e in self.other_changes
            ],
        }


def structured_diff(project_root: Path, rev: str = "HEAD~1") -> StructuredDiff:
    """Compute a structured semantic diff between `rev` and HEAD.

    Spec §10.5: returns a StructuredDiff with categorized changes
    (flows/resources/tests added/modified/removed + other).
    """
    project_root = project_root.resolve()

    changes = _get_changed_files(project_root, rev)
    head_sha = _git_sha(project_root, "HEAD")
    base_sha = _git_sha(project_root, rev)

    diff = StructuredDiff(base_sha=base_sha, head_sha=head_sha)

    for status, path in changes:
        if path.startswith("flows/") and path.endswith("flow.yaml"):
            _categorize_flow(diff, status, path)
        elif path.startswith("flows/") and "/resources/" in path:
            _categorize_resource(diff, status, path)
        elif path.startswith("flows/") and "/tests/" in path and path.endswith(".yaml"):
            _categorize_test(diff, status, path)
        else:
            diff.other_changes.append(
                DiffEntry(
                    path=path,
                    status=_normalize_status(status),
                    category="other",
                )
            )

    return diff


def semantic_diff(project_root: Path, rev: str = "HEAD~1") -> str:
    """Show what changed between `rev` and HEAD, expressed in IR terms.

    Spec §10.5. Returns a human-readable summary string.
    """
    diff = structured_diff(project_root, rev)

    if diff.total_changes == 0:
        return "no changes"

    lines = [f"Project diff: {diff.base_sha} → {diff.head_sha}", ""]

    if diff.flows_added:
        lines.append("Added flows:")
        for p in diff.flows_added:
            lines.append(f"  + {p}")
    if diff.flows_modified:
        lines.append("Modified flows:")
        for p in diff.flows_modified:
            lines.append(f"  ~ {p}")
    if diff.flows_removed:
        lines.append("Removed flows:")
        for p in diff.flows_removed:
            lines.append(f"  - {p}")

    if diff.resources_added:
        lines.append("Added resources:")
        for p in diff.resources_added:
            lines.append(f"  + {p}")
    if diff.resources_modified:
        lines.append("Modified resources:")
        for p in diff.resources_modified:
            lines.append(f"  ~ {p}")
    if diff.resources_removed:
        lines.append("Removed resources:")
        for p in diff.resources_removed:
            lines.append(f"  - {p}")

    if diff.tests_added:
        lines.append("Added tests:")
        for p in diff.tests_added:
            lines.append(f"  + {p}")
    if diff.tests_modified:
        lines.append("Modified tests:")
        for p in diff.tests_modified:
            lines.append(f"  ~ {p}")
    if diff.tests_removed:
        lines.append("Removed tests:")
        for p in diff.tests_removed:
            lines.append(f"  - {p}")

    if diff.other_changes:
        lines.append("Other changes:")
        for e in diff.other_changes:
            sym = {"added": "+", "modified": "~", "removed": "-", "renamed": "R"}.get(e.status, "?")
            lines.append(f"  {sym} {e.path}")

    lines.append("")
    lines.append("Run `oiw validate --strict` and `oiw test --all` for full review.")
    return "\n".join(lines)


def _categorize_flow(diff: StructuredDiff, status: str, path: str) -> None:
    normalized = _normalize_status(status)
    if normalized == "added":
        diff.flows_added.append(path)
    elif normalized == "removed":
        diff.flows_removed.append(path)
    else:
        diff.flows_modified.append(path)


def _categorize_resource(diff: StructuredDiff, status: str, path: str) -> None:
    normalized = _normalize_status(status)
    if normalized == "added":
        diff.resources_added.append(path)
    elif normalized == "removed":
        diff.resources_removed.append(path)
    else:
        diff.resources_modified.append(path)


def _categorize_test(diff: StructuredDiff, status: str, path: str) -> None:
    normalized = _normalize_status(status)
    if normalized == "added":
        diff.tests_added.append(path)
    elif normalized == "removed":
        diff.tests_removed.append(path)
    else:
        diff.tests_modified.append(path)


def _normalize_status(status: str) -> str:
    """Normalize git status codes to added/modified/removed/renamed."""
    if status.startswith("A"):
        return "added"
    if status.startswith("D"):
        return "removed"
    if status.startswith("R"):
        return "renamed"
    return "modified"


def _get_changed_files(project_root: Path, rev: str) -> list[tuple[str, str]]:
    """Run `git diff --name-status` and parse the output."""
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "diff", "--name-status", rev, "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return _parse_name_status(result.stdout)


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
