"""Import report.

Spec ref: §8.3 (Import Report Format).
"""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass
class RecognizedComponent:
    component: str
    fidelity: str


@dataclasses.dataclass
class PreservedOpaque:
    vendor_extension: str
    location: str


@dataclasses.dataclass
class UnsupportedComponent:
    component: str
    reason: str


@dataclasses.dataclass
class ImportReport:
    status: str  # FULL | PARTIAL | FAILED
    target_profile: str
    recognized: list[RecognizedComponent] = dataclasses.field(default_factory=list)
    preserved_opaque: list[PreservedOpaque] = dataclasses.field(default_factory=list)
    unsupported: list[UnsupportedComponent] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)
    digest: str | None = None
    source_archive: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "importResult": {
                "status": self.status,
                "targetProfile": self.target_profile,
                "recognized": [dataclasses.asdict(r) for r in self.recognized],
                "preservedOpaque": [dataclasses.asdict(p) for p in self.preserved_opaque],
                "unsupported": [dataclasses.asdict(u) for u in self.unsupported],
                "warnings": self.warnings,
                "digest": self.digest,
                "sourceArchive": self.source_archive,
            }
        }


def format_import_report(report: ImportReport) -> str:
    """Human-readable import report (spec §8.3)."""
    lines = [
        f"import: status={report.status}  target={report.target_profile}",
        f"  source: {report.source_archive}",
        f"  digest: {report.digest}",
    ]
    if report.recognized:
        lines.append("  recognized:")
        for r in report.recognized:
            lines.append(f"    - {r.component} (fidelity={r.fidelity})")
    if report.preserved_opaque:
        lines.append("  preservedOpaque:")
        for p in report.preserved_opaque:
            lines.append(f"    - {p.vendor_extension} -> {p.location}")
    if report.unsupported:
        lines.append("  unsupported:")
        for u in report.unsupported:
            lines.append(f"    - {u.component}: {u.reason}")
    if report.warnings:
        lines.append("  warnings:")
        for w in report.warnings:
            lines.append(f"    - {w}")
    return "\n".join(lines)
