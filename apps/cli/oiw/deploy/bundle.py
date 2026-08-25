"""Deterministic ZIP bundling of a build directory (WP-08 PR-9 / D-004).

The export compiler emits an OIW-format build DIRECTORY under
`<project>/dist/`. Uploading to the tenant needs bytes. This module zips
that directory deterministically (sorted entries, fixed timestamps) and
returns the payload + its sha256 digest so the deploy pipeline uploads
REAL content instead of the placeholder bytes the old mock seam sent.

NOTE (honesty): until the Phase 4 CPI-bundle exporter lands, these bytes
are the OIW IR bundle — fine for proving the update-only write path
against a scratch package, NOT yet a CPI-openable iFlow. That boundary
is documented in docs/plans/hands-free-roadmap.md (Phase 4).
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path


def zip_build_dir(build_dir: Path) -> tuple[bytes, str]:
    """Zip every file under build_dir deterministically.

    Returns (archive_bytes, "sha256:<hex>"). Entry order and timestamps
    are fixed so identical trees produce identical bytes.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(p for p in build_dir.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(path.relative_to(build_dir).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())
    data = buf.getvalue()
    return data, "sha256:" + hashlib.sha256(data).hexdigest()


def find_build_dir(project_path: Path) -> Path:
    """Locate the build output directory under <project>/dist/.

    Exactly one build dir is required — ambiguity fails loudly rather
    than uploading the wrong tree.
    """
    dist = project_path / "dist"
    if not dist.is_dir():
        raise FileNotFoundError(f"no dist/ directory under {project_path} — run `oiw build` first")
    candidates = sorted(d for d in dist.iterdir() if d.is_dir() and not d.name.startswith("."))
    if len(candidates) != 1:
        names = ", ".join(c.name for c in candidates) or "(none)"
        raise FileNotFoundError(
            f"expected exactly one build directory under {dist}, found: {names}. "
            "Pass --build-dir explicitly."
        )
    return candidates[0]


__all__ = ["find_build_dir", "zip_build_dir"]
