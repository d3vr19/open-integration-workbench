"""P5a-M3 parity suite — the honesty instrument.

Verdict taxonomy: agreed | mismatched | pending-oracle | stale-oracle |
unsupported | no-local-tests. Only fresh-oracle + locally-runnable cases
enter the agreement ratio; everything else stays visible.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml
from click.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.cli import main  # noqa: E402
from oiw.parity import evaluate_case, load_corpus, run_parity  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_engine_real_flag import _write_mini_project  # noqa: E402

NOW = datetime(2026, 8, 26, tzinfo=UTC)


def _cal(path: Path, *, status: str = "STARTED", sent: bool = True,
         rows: int = 1, age_h: float = 2.0) -> None:
    payload = dict(
        _cal_payload(status, sent, rows),
        startedAt=_iso_minus(age_h),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"calibration": payload}))


def _cal_payload(status: str, sent: bool, rows: int) -> dict:
    return {
        "packageId": "P", "artifactId": "a", "uploadedOk": True,
        "deployAccepted": True, "trackingUuid": None,
        "finalStatus": status, "errorDetail": None if status == "STARTED" else "boom",
        "messageSent": sent, "httpResponseStatus": 200 if sent else None,
        "mplRows": [
            {"MessageGuid": f"g{i}", "Status": "COMPLETED", "CustomStatus": "COMPLETED",
             "IntegrationFlowName": "a", "LogStart": "/Date(0)/"}
            for i in range(rows)
        ],
        "startedAt": "", "finishedAt": "",
    }


def _iso_minus(hours: float) -> str:
    from datetime import timedelta

    return (NOW - timedelta(hours=hours)).isoformat()


def _build_repo(tmp_path: Path) -> tuple[Path, Path]:
    """repo/ with a passing mini project + corpus dir; returns (repo_root, manifest)."""
    repo = tmp_path / "repo"
    _write_mini_project(repo / "proj-pass")
    corpus_dir = repo / "packages" / "parity-corpus"
    corpus_dir.mkdir(parents=True)
    manifest = corpus_dir / "manifest.yaml"
    manifest.write_text("spec:\n  cases: []\n")
    return repo, manifest


def test_load_corpus_reads_defaults_and_cases(tmp_path):
    repo, manifest = _build_repo(tmp_path)
    manifest.write_text(yaml.safe_dump({
        "spec": {
            "defaults": {"maxOracleAgeHours": 24},
            "cases": [{"name": "c1", "project": "proj-pass"}],
        }
    }))
    cases, max_age = load_corpus(manifest)
    assert max_age == 24.0
    assert len(cases) == 1 and cases[0].name == "c1"


def test_agreed_when_local_pass_and_oracle_message_completed(tmp_path):
    repo, _ = _build_repo(tmp_path)
    cal = repo / "reports" / "ok.yaml"
    _cal(cal, status="STARTED", sent=True, rows=1, age_h=2.0)
    case = evaluate_case(
        type("C", (), {"name": "x", "project": Path("proj-pass"), "artifact_id": "a",
                       "calibration": cal.relative_to(repo), "test": None})(),
        repo, now=NOW,
    )
    assert case["verdict"] == "agreed"


def test_mismatched_when_local_pass_but_oracle_error(tmp_path):
    repo, _ = _build_repo(tmp_path)
    cal = repo / "reports" / "bad.yaml"
    _cal(cal, status="ERROR", sent=False, rows=0, age_h=2.0)
    case = evaluate_case(
        type("C", (), {"name": "x", "project": Path("proj-pass"), "artifact_id": "a",
                       "calibration": cal.relative_to(repo), "test": None})(),
        repo, now=NOW,
    )
    assert case["verdict"] == "mismatched"
    assert "local=PASS" in case.get("details", "")


def test_pending_oracle_when_no_report(tmp_path):
    repo, _ = _build_repo(tmp_path)
    case = evaluate_case(
        type("C", (), {"name": "x", "project": Path("proj-pass"), "artifact_id": None,
                       "calibration": None, "test": None})(),
        repo, now=NOW,
    )
    assert case["verdict"] == "pending-oracle"


def test_stale_oracle_excluded_from_ratio(tmp_path):
    repo, _ = _build_repo(tmp_path)
    cal = repo / "reports" / "old.yaml"
    _cal(cal, status="STARTED", sent=True, rows=1, age_h=200.0)
    spec = type("C", (), {"name": "x", "project": Path("proj-pass"), "artifact_id": "a",
                          "calibration": cal.relative_to(repo), "test": None})()
    case = evaluate_case(spec, repo, now=NOW, max_oracle_age_hours=168.0)
    assert case["verdict"] == "stale-oracle"


def test_unsupported_local_run_is_refused_not_mismatched(tmp_path):
    repo, _ = _build_repo(tmp_path)
    _write_mini_project(repo / "proj-stub", nodes=[
        {"id": "gather-orders", "type": "gather", "config": {}, "fidelity": "simulated"},
    ])
    cal = repo / "reports" / "ok.yaml"
    _cal(cal, status="STARTED", sent=True, rows=1, age_h=2.0)
    case = evaluate_case(
        type("C", (), {"name": "x", "project": Path("proj-stub"), "artifact_id": "a",
                       "calibration": cal.relative_to(repo), "test": None})(),
        repo, now=NOW,
    )
    assert case["verdict"] == "unsupported"
    assert case["localStatus"] == "UNSUPPORTED"


def test_run_parity_publishes_yaml_with_gate_math(tmp_path):
    repo, manifest = _build_repo(tmp_path)
    cal_ok = repo / "reports" / "ok.yaml"
    _cal(cal_ok, status="STARTED", sent=True, rows=1, age_h=2.0)
    cal_bad = repo / "reports" / "bad.yaml"
    _cal(cal_bad, status="ERROR", sent=False, rows=0, age_h=2.0)
    manifest.write_text(yaml.safe_dump({"spec": {"defaults": {"maxOracleAgeHours": 168}, "cases": [
        {"name": "agree-case", "project": "proj-pass", "calibration": str(cal_ok.relative_to(repo))},
        {"name": "mismatch-case", "project": "proj-pass", "calibration": str(cal_bad.relative_to(repo))},
        {"name": "pending-case", "project": "proj-pass"},
    ]}}))
    out = tmp_path / "out" / "sim-parity.yaml"
    report = run_parity(manifest, out, repo_root=repo, now=NOW)

    s = report["sim_parity"]
    assert s["agreement"]["comparable"] == 2
    assert s["agreement"]["agreed"] == 1
    assert s["agreement"]["ratio"] == 0.5
    assert s["gate"]["passed"] is False  # <10 comparable even at 50%
    verdicts = {c["name"]: c["verdict"] for c in s["cases"]}
    assert verdicts == {
        "agree-case": "agreed",
        "mismatch-case": "mismatched",
        "pending-case": "pending-oracle",
    }
    published = yaml.safe_load(out.read_text())
    assert published["sim_parity"]["agreement"]["ratio"] == 0.5


def test_cli_parity_command_runs_repo_corpus(tmp_path):
    """End-to-end on the REAL repo corpus: publishes the honest baseline."""
    runner = CliRunner()
    out = tmp_path / "parity.yaml"
    res = runner.invoke(main, [
        "parity",
        "--corpus", str(REPO_ROOT / "packages" / "parity-corpus" / "manifest.yaml"),
        "--out", str(out),
        # Keep the repo tree clean: mismatch candidates go to tmp (C-2
        # wiring files candidates next to the corpus by default).
        "--candidates-dir", str(tmp_path / "cands"),
    ])
    assert res.exit_code == 0, res.output
    assert "gate" in res.output
    payload = yaml.safe_load(out.read_text())["sim_parity"]
    names = {c["name"] for c in payload["cases"]}
    assert "heldout-order-async-smoke" in names


def test_cli_parity_enforce_gate_exits_nonzero(tmp_path):
    runner = CliRunner()
    res = runner.invoke(main, [
        "parity",
        "--corpus", str(REPO_ROOT / "packages" / "parity-corpus" / "manifest.yaml"),
        "--out", str(tmp_path / "p.yaml"),
        "--candidates-dir", str(tmp_path / "cands"),
        "--enforce-gate",
    ])
    assert res.exit_code == 1  # v0 baseline: gate open until fresh oracle data
