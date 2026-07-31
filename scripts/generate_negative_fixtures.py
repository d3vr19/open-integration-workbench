#!/usr/bin/env python3
"""Generate negative test fixtures for the safe archive inspector.

Spec ref: §8.5 (negative fixtures), §8.2 (Safe Archive Reader), §16.1 threat 1.

Generates:
  - zip-bomb.zip          small compressed file decompressing to >100MB
  - path-traversal.zip    contains entries with ../path-traversal names
  - corrupt-manifest.zip  invalid zip

Run from the repo root: python scripts/generate_negative_fixtures.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path


NEG_DIR = Path(__file__).resolve().parent.parent / "packages" / "test-fixtures" / "negative"


def make_zip_bomb() -> None:
    """A real zip bomb: a single 100 MB zero-entry that compresses very small."""
    path = NEG_DIR / "zip-bomb.zip"
    # 100 MB of zeros -> compresses to ~100 KB
    payload = b"\0" * (100 * 1024 * 1024)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb.dat", payload)
    print(f"wrote {path} ({path.stat().st_size} bytes compressed, 100MB uncompressed)")


def make_path_traversal() -> None:
    """Archive with `../escape.txt` entry."""
    path = NEG_DIR / "path-traversal.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../escape.txt", "should be rejected")
        zf.writestr("legit.txt", "ok")
    print(f"wrote {path}")


def make_corrupt_manifest() -> None:
    """Invalid zip file."""
    path = NEG_DIR / "corrupt-manifest.zip"
    path.write_bytes(b"PK\x03\x04 not actually a valid zip body")
    print(f"wrote {path}")


def main() -> None:
    NEG_DIR.mkdir(parents=True, exist_ok=True)
    make_zip_bomb()
    make_path_traversal()
    make_corrupt_manifest()


if __name__ == "__main__":
    main()
