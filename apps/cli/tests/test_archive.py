"""Tests for the safe archive inspector (spec §8.2, §16.1 threat 1)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from oiw.archive import ArchiveSafetyError, inspect_archive

FIXTURES = Path(__file__).resolve().parent.parent.parent.parent / "packages" / "test-fixtures"


def _make_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)


def test_inspect_valid_archive(tmp_path: Path) -> None:
    p = tmp_path / "ok.zip"
    _make_zip(p, {"flow.yaml": "kind: IntegrationFlow\n", "diagram.json": "{}\n"})
    manifest = inspect_archive(p)
    assert manifest.entry_count == 2
    assert manifest.compressed_size > 0
    assert manifest.uncompressed_size > 0
    assert manifest.digest.startswith("sha256:")
    assert manifest.compression_ratio > 0


def test_inspect_path_traversal_rejected(tmp_path: Path) -> None:
    p = tmp_path / "evil.zip"
    _make_zip(p, {"../escape.txt": "should be rejected", "legit.txt": "ok"})
    with pytest.raises(ArchiveSafetyError, match="path traversal"):
        inspect_archive(p)


def test_inspect_absolute_path_rejected(tmp_path: Path) -> None:
    p = tmp_path / "abs.zip"
    _make_zip(p, {"/etc/passwd": "nope"})
    with pytest.raises(ArchiveSafetyError, match="absolute path"):
        inspect_archive(p)


def test_inspect_drive_letter_rejected(tmp_path: Path) -> None:
    p = tmp_path / "drive.zip"
    _make_zip(p, {"C:/windows/system32/evil.txt": "nope"})
    with pytest.raises(ArchiveSafetyError, match="drive-letter"):
        inspect_archive(p)


def test_inspect_corrupt_zip_rejected(tmp_path: Path) -> None:
    p = tmp_path / "corrupt.zip"
    p.write_bytes(b"PK\x03\x04 not actually a valid zip body")
    with pytest.raises(ArchiveSafetyError, match="not a valid zip"):
        inspect_archive(p)


def test_inspect_zip_bomb_rejected(tmp_path: Path) -> None:
    """A real zip bomb: high compression ratio triggers the safety check."""
    p = tmp_path / "bomb.zip"
    payload = b"\0" * (50 * 1024 * 1024)  # 50 MB of zeros, compresses to ~50 KB
    _make_zip(p, {"bomb.dat": payload})
    with pytest.raises(ArchiveSafetyError, match="compression ratio"):
        inspect_archive(p)


def test_inspect_negative_fixtures() -> None:
    """The committed negative fixtures MUST all be rejected."""
    negative_dir = FIXTURES / "negative"
    if not negative_dir.exists():
        pytest.skip("negative fixtures not yet generated (run scripts/generate_negative_fixtures.py)")
    for fixture in ("zip-bomb.zip", "path-traversal.zip", "corrupt-manifest.zip"):
        path = negative_dir / fixture
        if not path.exists():
            pytest.skip(f"{fixture} not found")
        with pytest.raises(ArchiveSafetyError):
            inspect_archive(path)


def test_inspect_golden_fixture_accepted() -> None:
    """The committed golden fixture MUST be accepted."""
    path = FIXTURES / "minimal" / "https-content-modifier-http" / "source.zip"
    if not path.exists():
        pytest.skip("golden fixture not yet generated (run scripts/generate_golden_fixture.py)")
    manifest = inspect_archive(path)
    assert manifest.entry_count >= 1
    assert manifest.digest.startswith("sha256:")


def test_inspect_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ArchiveSafetyError, match="not found"):
        inspect_archive(tmp_path / "nonexistent.zip")


def test_inspect_size_limit(tmp_path: Path) -> None:
    p = tmp_path / "toobig.zip"
    _make_zip(p, {"x.txt": b"x"})
    with pytest.raises(ArchiveSafetyError, match="exceeds max"):
        inspect_archive(p, max_compressed=10)
