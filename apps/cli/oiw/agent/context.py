"""Project context for the agent pipeline.

A thin wrapper around `oiw.project.Project` + `oiw.git_ops` that exposes
the bits the agent needs:
  - project_id, root path
  - current git HEAD sha
  - flow listing + IR truncation
  - resource tree (file listing)
  - validation state snapshot

The wrapper is intentionally minimal: it does NOT cache. Every call
re-reads from disk so the agent always sees the current state. This
matters because the executor mutates the project between steps.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProjectContext:
    """Lightweight view of a project on disk."""

    project_id: str
    root: Path
    _head_cache: str | None = field(default=None, repr=False)

    @classmethod
    def load(cls, project_path: Path | str, project_id: str | None = None) -> ProjectContext:
        """Load a project context from a directory.

        `project_path` is the directory containing the project's files
        (oiw.yaml, flows/, environments/, ...). `project_id` defaults to
        the directory name.
        """
        root = Path(project_path).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"project directory not found: {root}")
        pid = project_id or root.name
        return cls(project_id=pid, root=root)

    def git_head(self) -> str:
        """Return the short HEAD sha of the project's git repo.

        Returns 'unknown' if the directory is not a git repo (e.g. tests
        that didn't init git). Cached for the lifetime of the context
        instance — call `.invalidate_head()` to force a re-read.
        """
        if self._head_cache is not None:
            return self._head_cache
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            self._head_cache = result.stdout.strip()
        except Exception:
            self._head_cache = "unknown"
        return self._head_cache

    def invalidate_head(self) -> None:
        """Force the next git_head() call to re-read."""
        self._head_cache = None

    def list_flows(self) -> list[str]:
        """Return flow IDs (directory names under flows/)."""
        flows_dir = self.root / "flows"
        if not flows_dir.is_dir():
            return []
        return sorted(d.name for d in flows_dir.iterdir() if d.is_dir())

    def get_flow_ir(self, flow_id: str, max_chars: int = 32000) -> dict[str, Any] | None:
        """Load and return a flow's IR (flow.yaml parsed).

        Truncated to `max_chars` of the YAML source to keep prompt size
        bounded. Returns None if the flow doesn't exist.
        """
        flow_yaml = self.root / "flows" / flow_id / "flow.yaml"
        if not flow_yaml.is_file():
            return None
        try:
            import yaml

            text = flow_yaml.read_text(encoding="utf-8")
            if len(text) > max_chars:
                text = text[:max_chars] + "\n# ... (truncated)"
            return yaml.safe_load(text)
        except Exception:
            return None

    def resource_tree(self, max_entries: int = 200) -> list[str]:
        """Return a sorted list of resource paths under the project.

        Includes flow.yaml, diagram.json, resources/, tests/, etc.
        Bounded to `max_entries` to keep prompt size sane.
        """
        out: list[str] = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file():
                continue
            if any(part in {".git", "__pycache__", ".oiw", "node_modules"} for part in p.parts):
                continue
            rel = p.relative_to(self.root).as_posix()
            out.append(rel)
            if len(out) >= max_entries:
                out.append("... (truncated)")
                break
        return out

    def snapshot(self) -> dict[str, Any]:
        """A JSON-serializable summary used as a trajectory observation."""
        return {
            "projectId": self.project_id,
            "head": self.git_head(),
            "flows": self.list_flows(),
            "resourceCount": len(self.resource_tree()),
        }

    def to_prompt_context(self, flow_id: str | None = None) -> str:
        """Build a compact string for inclusion in an LLM prompt."""
        parts = [
            f"Project: {self.project_id}",
            f"HEAD: {self.git_head()}",
            f"Flows: {', '.join(self.list_flows()) or '(none)'}",
        ]
        if flow_id:
            ir = self.get_flow_ir(flow_id)
            if ir is not None:
                parts.append(f"Flow IR ({flow_id}):\n" + json.dumps(ir, indent=2, default=str)[:8000])
        parts.append("Resource tree (first 100):\n  " + "\n  ".join(self.resource_tree()[:100]))
        return "\n".join(parts)


__all__ = ["ProjectContext"]
