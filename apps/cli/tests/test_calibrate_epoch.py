"""MPL epoch-filter tests (calibrate.py, live finding 2026-09-02).

An artifact redeployed many times (bisection history) carries stale
FAILED rows; the epoch filter keeps only rows from the current run's
window so verdicts reflect THIS deploy, not history.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.tenant.calibrate import _epoch_ms  # noqa: E402


def test_epoch_ms_parses_iso_with_tz() -> None:
    assert _epoch_ms("2026-09-02T12:00:00+00:00") == 1788350400000.0


def test_epoch_ms_parses_naive_as_utc() -> None:
    assert _epoch_ms("2026-09-02T12:00:00") == 1788350400000.0


def test_epoch_ms_garbage_is_zero() -> None:
    assert _epoch_ms("not-a-date") == 0.0
    assert _epoch_ms("") == 0.0
