"""Archive route. Spec §21.1, §8.2."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from oiw.archive import ArchiveSafetyError, inspect_archive

from ..models import ArchiveEntry, ArchiveManifest, Error

router = APIRouter(prefix="/api/v1", tags=["Archive"])


@router.post("/archive/inspect", response_model=ArchiveManifest)
async def inspect_archive_endpoint(archive: UploadFile = File(...)) -> ArchiveManifest:  # noqa: B008
    """Safely inspect an uploaded archive without extracting it to disk."""
    # Save to a temp file (streaming inspection would be better but requires
    # a streaming zip reader; the current oiw.archive.inspect_archive takes a path).
    tmp_dir = Path(tempfile.mkdtemp(prefix="oiw-archive-"))
    tmp_file = tmp_dir / (archive.filename or "upload.zip")
    try:
        with tmp_file.open("wb") as f:
            shutil.copyfileobj(archive.file, f)
        manifest = inspect_archive(tmp_file)
        return ArchiveManifest(
            path=str(archive.filename or tmp_file.name),
            entry_count=manifest.entry_count,
            compressed_size=manifest.compressed_size,
            uncompressed_size=manifest.uncompressed_size,
            compression_ratio=manifest.compression_ratio,
            digest=manifest.digest,
            warnings=manifest.warnings,
            entries=[
                ArchiveEntry(
                    name=e.name,
                    compressed_size=e.compressed_size,
                    uncompressed_size=e.uncompressed_size,
                    is_dir=e.is_dir,
                )
                for e in manifest.entries
            ],
        )
    except ArchiveSafetyError as exc:
        raise HTTPException(
            status_code=400,
            detail=Error(message=f"archive safety check failed: {exc}").model_dump(),
        ) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
