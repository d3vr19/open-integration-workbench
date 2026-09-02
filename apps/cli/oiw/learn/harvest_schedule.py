"""C-3: pattern-book crawler schedule — harvest stops being one-shot.

A tiny, dependency-free freshness gate for `oiw emg harvest`:

  - state lives in the pattern book itself (census.yaml `harvestedAt`)
    plus a sidecar `packages/pattern-book/harvest-state.yaml` recording
    the last crawl + schedule config;
  - `harvest_due()` answers "is a crawl warranted right now?" using a
    TTL (default 7 days) — a scheduled job (cron, systemd timer, GitHub
    Actions schedule) can simply run `oiw emg harvest --if-due` and it
    becomes a no-op until the pattern book goes stale;
  - all timestamps are UTC ISO-8601; malformed state files are treated
    as "never harvested" (loud, honest, self-healing on next crawl).

Laws honored: read-only tenant crawling, never CI, never on a real
tenant from an automated context (the caller passes the adapter; the
schedule only decides WHEN, the operator still decides HOW).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

DEFAULT_TTL_DAYS = 7
STATE_FILENAME = "harvest-state.yaml"


@dataclass
class HarvestSchedule:
    """Freshness state for the pattern-book harvester."""

    last_harvest_at: datetime | None = None
    artifacts_scanned: int = 0
    distinct_shapes: int = 0
    ttl_days: float = DEFAULT_TTL_DAYS

    def is_due(self, now: datetime | None = None) -> bool:
        """True when no harvest has happened or the TTL expired."""
        if self.last_harvest_at is None:
            return True
        now = now or datetime.now(tz=UTC)
        last = self.last_harvest_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return (now - last) >= timedelta(days=self.ttl_days)

    def next_due_at(self) -> datetime | None:
        if self.last_harvest_at is None:
            return None
        last = self.last_harvest_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return last + timedelta(days=self.ttl_days)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule": {
                "lastHarvestAt": self.last_harvest_at.isoformat() if self.last_harvest_at else None,
                "artifactsScanned": self.artifacts_scanned,
                "distinctShapes": self.distinct_shapes,
                "ttlDays": self.ttl_days,
            }
        }


def _parse_ts(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def load_schedule(pattern_book_dir: Path) -> HarvestSchedule:
    """Load the harvest schedule sidecar.

    Falls back to census.yaml's `harvestedAt` when the sidecar has not
    been written yet (back-compat with the one-shot harvest of session 7).
    Malformed values degrade to "never harvested" — the next crawl
    self-heals the state file.
    """
    sidecar = pattern_book_dir / STATE_FILENAME
    data: dict[str, Any] = {}
    if sidecar.is_file():
        try:
            data = yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            data = {}
    sched = (data or {}).get("schedule") or {}

    last = _parse_ts(sched.get("lastHarvestAt"))
    scanned = int(sched.get("artifactsScanned") or 0)
    shapes = int(sched.get("distinctShapes") or 0)
    try:
        ttl = float(sched.get("ttlDays") or DEFAULT_TTL_DAYS)
    except (TypeError, ValueError):
        ttl = DEFAULT_TTL_DAYS

    if last is None:
        # Back-compat: read census.yaml harvestedAt (naive local time in
        # the harvester; treat as UTC).
        census = pattern_book_dir / "census.yaml"
        if census.is_file():
            try:
                c = yaml.safe_load(census.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                c = {}
            last = _parse_ts((c or {}).get("harvestedAt"))
            scanned = scanned or int((c or {}).get("artifactsScanned") or 0)
            shapes = shapes or int((c or {}).get("distinctShapes") or 0)

    return HarvestSchedule(
        last_harvest_at=last,
        artifacts_scanned=scanned,
        distinct_shapes=shapes,
        ttl_days=ttl,
    )


def save_schedule(pattern_book_dir: Path, schedule: HarvestSchedule) -> Path:
    """Persist the schedule sidecar (atomic-ish write; small file)."""
    pattern_book_dir.mkdir(parents=True, exist_ok=True)
    path = pattern_book_dir / STATE_FILENAME
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(schedule.to_dict(), sort_keys=True), encoding="utf-8")
    path.write_text(tmp.read_text(encoding="utf-8"), encoding="utf-8")
    tmp.unlink(missing_ok=True)
    return path


def harvest_due(pattern_book_dir: Path, *, ttl_days: float | None = None) -> HarvestSchedule:
    """Load the schedule (optionally overriding TTL) — caller checks .is_due()."""
    schedule = load_schedule(pattern_book_dir)
    if ttl_days is not None:
        schedule.ttl_days = float(ttl_days)
    return schedule


__all__ = [
    "DEFAULT_TTL_DAYS",
    "HarvestSchedule",
    "harvest_due",
    "load_schedule",
    "save_schedule",
    "STATE_FILENAME",
]
