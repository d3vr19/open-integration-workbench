"""Safe archive inspector.

Spec ref: §8.2 (compiler pipeline step 1: Safe Archive Reader), §16.1 threat 1
(zip bomb, path traversal).

Defenses:
  - Max compressed size (default 256 MB)
  - Max uncompressed size (default 1 GB)
  - Max entry count (default 10 000)
  - Compression ratio cap (default 100:1) -> zip bomb detection
  - Path traversal rejection: no `..`, no absolute paths, no leading drive letters
  - Symlink rejection
  - Manifest digest (sha256)
"""

from __future__ import annotations

import dataclasses
import hashlib
import zipfile
from pathlib import Path


class ArchiveSafetyError(Exception):
    """Raised when an archive violates a safety constraint."""


@dataclasses.dataclass
class ArchiveEntry:
    name: str
    compressed_size: int
    uncompressed_size: int
    is_dir: bool


@dataclasses.dataclass
class ArchiveManifest:
    path: Path
    entries: list[ArchiveEntry]
    entry_count: int
    compressed_size: int
    uncompressed_size: int
    compression_ratio: float
    digest: str
    warnings: list[str] = dataclasses.field(default_factory=list)


# Defaults — overridable by callers if needed
MAX_COMPRESSED_BYTES = 256 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_ENTRY_COUNT = 10_000
MAX_COMPRESSION_RATIO = 100.0


def inspect_archive(
    path: Path,
    *,
    max_compressed: int = MAX_COMPRESSED_BYTES,
    max_uncompressed: int = MAX_UNCOMPRESSED_BYTES,
    max_entries: int = MAX_ENTRY_COUNT,
    max_ratio: float = MAX_COMPRESSION_RATIO,
) -> ArchiveManifest:
    """Inspect a zip archive safely. Does not extract to disk."""
    if not path.exists() or not path.is_file():
        raise ArchiveSafetyError(f"archive not found or not a file: {path}")

    file_size = path.stat().st_size
    if file_size > max_compressed:
        raise ArchiveSafetyError(f"archive size {file_size} bytes exceeds max {max_compressed} bytes")

    digest = _sha256_file(path)
    entries: list[ArchiveEntry] = []
    total_compressed = 0
    total_uncompressed = 0
    warnings: list[str] = []

    try:
        with zipfile.ZipFile(path, "r") as zf:
            infos = zf.infolist()
            if len(infos) > max_entries:
                raise ArchiveSafetyError(f"archive has {len(infos)} entries; max {max_entries}")
            for info in infos:
                _validate_entry_name(info.filename)
                if info.create_system == 3 and (info.external_attr >> 16) & 0o170000 == 0o120000:
                    # Symlink on unix
                    raise ArchiveSafetyError(f"symlinks are not allowed: {info.filename}")
                entry = ArchiveEntry(
                    name=info.filename,
                    compressed_size=info.compress_size,
                    uncompressed_size=info.file_size,
                    is_dir=info.is_dir(),
                )
                entries.append(entry)
                total_compressed += info.compress_size
                total_uncompressed += info.file_size

                if info.file_size > max_uncompressed:
                    raise ArchiveSafetyError(
                        f"entry '{info.filename}' uncompressed size {info.file_size} exceeds max {max_uncompressed}"
                    )

    except zipfile.BadZipFile as exc:
        raise ArchiveSafetyError(f"not a valid zip archive: {exc}") from exc

    if total_uncompressed > max_uncompressed:
        raise ArchiveSafetyError(
            f"total uncompressed size {total_uncompressed} exceeds max {max_uncompressed}"
        )

    ratio = (total_uncompressed / total_compressed) if total_compressed > 0 else 0.0
    if ratio > max_ratio:
        raise ArchiveSafetyError(
            f"compression ratio {ratio:.1f}x exceeds max {max_ratio}x (possible zip bomb)"
        )

    if ratio > 50:
        warnings.append(f"high compression ratio {ratio:.1f}x — verify intent")

    return ArchiveManifest(
        path=path,
        entries=entries,
        entry_count=len(entries),
        compressed_size=total_compressed,
        uncompressed_size=total_uncompressed,
        compression_ratio=ratio,
        digest=digest,
        warnings=warnings,
    )


def _validate_entry_name(name: str) -> None:
    """Reject path traversal, absolute paths, drive letters."""
    if not name:
        raise ArchiveSafetyError("empty entry name")
    # Normalize separators
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        raise ArchiveSafetyError(f"absolute path in archive: {name}")
    # Drive letter (Windows)
    if len(normalized) > 1 and normalized[1] == ":":
        raise ArchiveSafetyError(f"drive-letter path in archive: {name}")
    # Path traversal
    parts = normalized.split("/")
    if ".." in parts:
        raise ArchiveSafetyError(f"path traversal in archive: {name}")


def _sha256_file(path: Path, chunk: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return f"sha256:{h.hexdigest()}"
