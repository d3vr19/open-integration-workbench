"""Git operations.

Spec ref: §11 (Git-Native Workflow), §11.3 (commit convention), §11.4 (generated files),
§12.1 (LLM never commits directly — must propose).
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path


@dataclasses.dataclass
class GitStatus:
    branch: str
    head_sha: str
    dirty: bool
    ahead: int
    last_build_digest: str | None
    last_build_target: str | None


@dataclasses.dataclass
class CommitProposal:
    message: str
    files: list[str]
    ai_provenance: dict | None = None


def git_status(project_root: Path) -> GitStatus:
    project_root = project_root.resolve()
    branch = _git(project_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip() or "HEAD"
    head_sha = _git(project_root, ["rev-parse", "--short", "HEAD"]).strip()

    # Dirty: any unstaged/untracked changes
    status_porcelain = _git(project_root, ["status", "--porcelain"])
    # Ignore dist/ and .oiw/ which are gitignored
    dirty_lines = [
        line
        for line in status_porcelain.splitlines()
        if line.strip() and not line.strip().split()[-1].startswith(("dist/", ".oiw/"))
    ]
    dirty = bool(dirty_lines)

    # Ahead: commits on HEAD not on upstream
    ahead = 0
    try:
        upstream = _git(project_root, ["rev-parse", "--abbrev-ref", "@{upstream}"]).strip()
        if upstream:
            count_str = _git(project_root, ["rev-list", "--count", f"{upstream}..HEAD"]).strip()
            ahead = int(count_str) if count_str.isdigit() else 0
    except subprocess.CalledProcessError:
        pass  # no upstream configured

    # Last build digest from .oiw/compiler.lock
    lock_path = project_root / ".oiw" / "compiler.lock"
    last_build_digest = None
    last_build_target = None
    if lock_path.exists():
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            last_build_digest = lock.get("digest")
            last_build_target = lock.get("targetProfile")
        except Exception:
            pass

    return GitStatus(
        branch=branch,
        head_sha=head_sha,
        dirty=dirty,
        ahead=ahead,
        last_build_digest=last_build_digest,
        last_build_target=last_build_target,
    )


def git_commit_proposal(
    project_root: Path, message: str, files: list[Path], ai_provenance: dict | None = None
) -> CommitProposal:
    """Build a commit proposal. Does NOT execute `git commit`.

    Spec ref: §12.1 — the LLM never edits files directly; all mutations go
    through typed patch operations, and commits require human approval.
    """
    project_root = project_root.resolve()
    normalized_files: list[str] = []
    for f in files:
        try:
            rel = f.resolve().relative_to(project_root)
            normalized_files.append(rel.as_posix())
        except ValueError:
            normalized_files.append(str(f))
    return CommitProposal(
        message=message,
        files=normalized_files,
        ai_provenance=ai_provenance,
    )


def _git(root: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout
