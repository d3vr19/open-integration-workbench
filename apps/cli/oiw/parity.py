"""P5a-M3 parity suite — the honesty instrument.

Runs each corpus case through the LOCAL engine in `real` mode and compares
the verdict against a CACHED tenant calibration report (`oiw tenant
calibrate` output; never live from this runner, never CI — blood law:
oracle cost + point-in-time verdicts, p5-p6-plan.md §6).

Agreement dimensions (plan §2 M3): deployable?, started?, message verdict.
Published metric: docs/emg/sim-parity.yaml — agreement ratio over COMPARABLE
cases only, with every excluded case visible and honestly labeled.

Gate (§3): ≥90% agreement on ≥10 comparable cases before breadth work.
The runner reports the gate; it does not silently enforce it (--enforce-gate).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .testing import run_tests

DEFAULT_MAX_ORACLE_AGE_HOURS = 168.0
GATE_THRESHOLD = 0.9
GATE_MIN_COMPARABLE = 10

CAVEATS = [
    "Oracle verdicts are POINT-IN-TIME (blood law, p5-p6-plan.md §6): a "
    "mismatch against an old report may reflect tenant drift or the "
    "deploy-rate wedge, not local infidelity.",
    "Comparable set counts only cases with fresh oracle MESSAGE evidence; "
    "pending/stale/unsupported cases are excluded from the ratio but listed.",
    "Corpus grows from observed mismatches and fresh calibrate runs only — " "never fabricated.",
]


@dataclasses.dataclass
class ParityCaseSpec:
    name: str
    project: Path  # relative to repo root
    artifact_id: str | None = None
    calibration: Path | None = None  # relative to repo root
    test: str | None = None
    # Listener case (P6 PD topology): a sender.processdirect artifact has
    # no HTTP endpoint to exercise — its tenant verdict is STARTED alone;
    # message evidence arrives via the CALLER's chain (both-artifacts
    # MPL COMPLETED, p6-demo.yaml). Comparable on STARTED when true.
    listener: bool = False


def load_corpus(manifest_path: Path) -> tuple[list[ParityCaseSpec], float]:
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    spec = raw.get("spec") or {}
    defaults = spec.get("defaults") or {}
    max_age = float(defaults.get("maxOracleAgeHours", DEFAULT_MAX_ORACLE_AGE_HOURS))
    cases = [
        ParityCaseSpec(
            name=str(c["name"]),
            project=Path(c["project"]),
            artifact_id=c.get("artifactId"),
            calibration=Path(c["calibration"]) if c.get("calibration") else None,
            test=c.get("test"),
            listener=bool(c.get("listener", False)),
        )
        for c in (spec.get("cases") or [])
    ]
    return cases, max_age


def _load_oracle(path: Path | None, repo_root: Path) -> dict[str, Any] | None:
    if path is None:
        return None
    full = repo_root / path
    if not full.exists():
        return None
    payload = yaml.safe_load(full.read_text(encoding="utf-8")) or {}
    return payload.get("calibration")


def _oracle_age_hours(cal: dict[str, Any], now: datetime) -> float | None:
    raw = str(cal.get("startedAt") or "").strip()
    if not raw:
        return None
    try:
        started = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return max(0.0, (now - started).total_seconds() / 3600.0)


def _oracle_verdict(cal: dict[str, Any]) -> dict[str, Any]:
    status = str(cal.get("finalStatus") or "UNKNOWN").upper()
    rows = cal.get("mplRows") or []
    completed = [r for r in rows if r.get("Status") == "COMPLETED"]
    message_completed = bool(cal.get("messageSent") and rows and len(completed) == len(rows))
    success = status == "STARTED" and message_completed
    return {
        "finalStatus": status,
        "messageSent": bool(cal.get("messageSent")),
        "mplRows": len(rows),
        "mplCompleted": len(completed),
        "success": success,
        "errorDetail": cal.get("errorDetail"),
    }


def evaluate_case(
    case: ParityCaseSpec,
    repo_root: Path,
    *,
    now: datetime | None = None,
    max_oracle_age_hours: float = DEFAULT_MAX_ORACLE_AGE_HOURS,
) -> dict[str, Any]:
    now = now or datetime.now(tz=UTC)
    row: dict[str, Any] = {
        "name": case.name,
        "project": str(case.project),
        "artifactId": case.artifact_id,
    }

    # --- local side (real engine) ---
    from .project import Project, ProjectError

    try:
        project = Project.load(repo_root / case.project)
    except ProjectError as exc:
        row.update({"localStatus": "PROJECT-ERROR", "verdict": "no-local-tests", "details": str(exc)})
        return row

    results = run_tests(project, test_name=case.test, engine="real")
    if not results:
        row.update(
            {
                "localStatus": "NO-LOCAL-TESTS",
                "verdict": "no-local-tests",
                "details": f"no FlowTests matched test={case.test!r}",
            }
        )
        return row

    local_passed = all(r.passed for r in results)
    blocked = all(r.real_engine_blocked for r in results)
    row["localPassed"] = local_passed
    row["localStatus"] = "UNSUPPORTED" if blocked else ("PASS" if local_passed else "FAIL")
    if blocked:
        row.update(
            {
                "verdict": "unsupported",
                "details": next(iter(r.failures[0] for r in results if r.failures), ""),
            }
        )
        return row

    # --- tenant side (cached calibration only) ---
    cal = _load_oracle(case.calibration, repo_root)
    if cal is None:
        row.update({"verdict": "pending-oracle", "details": "no cached calibration report for this case"})
        return row

    age = _oracle_age_hours(cal, now)
    oracle = _oracle_verdict(cal)
    row["oracle"] = {k: v for k, v in oracle.items() if k != "errorDetail"}
    row["oracleReportAgeHours"] = round(age, 2) if age is not None else None

    if age is not None and age > max_oracle_age_hours:
        row["verdict"] = "stale-oracle"
        return row

    if oracle["finalStatus"] == "STARTED" and not oracle["messageSent"]:
        if case.listener:
            # Listener case: STARTED IS the tenant verdict (PD senders have
            # no HTTP entrypoint; message evidence belongs to the caller's
            # chain). Comparable on STARTED == local PASS.
            agreed = local_passed  # oracle success dim = STARTED here
            row["verdict"] = "agreed" if agreed else "mismatched"
            if not agreed:
                row["details"] = f"local={row['localStatus']} vs oracle STARTED (listener form)"
            return row
        row["verdict"] = "pending-oracle-message"
        return row

    agreed = oracle["success"] == local_passed
    row["verdict"] = "agreed" if agreed else "mismatched"
    if not agreed:
        row["details"] = f"local={row['localStatus']} vs oracle={oracle['finalStatus']}" + (
            f" ({oracle['errorDetail']})" if oracle.get("errorDetail") else ""
        )
    return row


def run_parity(
    manifest_path: Path,
    out_path: Path | None = None,
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate the corpus and (optionally) publish sim-parity.yaml.

    repo_root anchors case-relative paths; defaults to the manifest's
    grandparent (convention: <repo>/packages/parity-corpus/manifest.yaml).
    """
    now = now or datetime.now(tz=UTC)
    repo_root = (repo_root or manifest_path.parent.parent.parent).resolve()
    cases, max_age = load_corpus(manifest_path)

    rows = [evaluate_case(c, repo_root, now=now, max_oracle_age_hours=max_age) for c in cases]
    comparable = [r for r in rows if r["verdict"] in ("agreed", "mismatched")]
    agreed = sum(1 for r in comparable if r["verdict"] == "agreed")
    ratio = (agreed / len(comparable)) if comparable else None
    gate_passed = (
        bool(comparable)
        and len(comparable) >= GATE_MIN_COMPARABLE
        and (ratio is not None and ratio >= GATE_THRESHOLD)
    )

    report = {
        "sim_parity": {
            "generatedAt": now.isoformat(),
            "corpus": str(manifest_path),
            "engine": "real",
            "cases": rows,
            "agreement": {
                "comparable": len(comparable),
                "agreed": agreed,
                "ratio": round(ratio, 4) if ratio is not None else None,
            },
            "gate": {
                "threshold": GATE_THRESHOLD,
                "minComparable": GATE_MIN_COMPARABLE,
                "passed": gate_passed,
            },
            "caveats": CAVEATS,
        }
    }
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(yaml.safe_dump(report, sort_keys=False), encoding="utf-8")
    return report


__all__ = [
    "ParityCaseSpec",
    "evaluate_case",
    "load_corpus",
    "run_parity",
]
