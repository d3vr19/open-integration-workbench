"""Tests for the oiw simulate CLI verb (WP-10 H10).

Spec / Task Acceptance:
1. `oiw simulate --project <p> --flow <f> --test smoke` runs the engine against
   the FlowTest named `smoke` and prints per-step trace entries (pass/fail + duration)
   + final exchange status; exit 0 on COMPLETED, 1 on FAILED, 2 on usage errors.
2. `--json` flag emits the full structured trace (same shape as simulate API payload).
3. `--engine real|simulated` flag (default simulated).
4. MPL-shaped records emitted under `--engine real` with `Origin=local-sim`.
5. No tenant access, no network (mock seam).
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from oiw.cli import main

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PROJECT = REPO_ROOT / "examples" / "weather-logger-async"


class TestSimulateCLI:
    def test_simulate_happy_path(self) -> None:
        runner = CliRunner()
        res = runner.invoke(
            main,
            [
                "simulate",
                "--project",
                str(EXAMPLE_PROJECT),
                "--flow",
                "weather-logger-async",
                "--test",
                "smoke",
            ],
        )
        assert res.exit_code == 0, res.output
        assert "sender-http" in res.output
        assert "rr-fetch" in res.output
        assert "add-context" in res.output
        assert "pd-terminator" in res.output
        assert "exchange status: COMPLETED" in res.output

    def test_simulate_json_flag(self) -> None:
        runner = CliRunner()
        res = runner.invoke(
            main,
            [
                "simulate",
                "--project",
                str(EXAMPLE_PROJECT),
                "--flow",
                "weather-logger-async",
                "--test",
                "smoke",
                "--json",
            ],
        )
        assert res.exit_code == 0, res.output
        data = json.loads(res.output)
        assert data["status"] == "COMPLETED"
        assert isinstance(data["trace"], list)
        assert len(data["trace"]) > 0
        assert "outbound_calls" in data
        assert "headers" in data
        assert "properties" in data
        first_trace = data["trace"][0]
        for key in (
            "node_id",
            "timestamp",
            "direction",
            "summary",
            "body_preview",
            "headers",
            "properties",
            "duration_ms",
            "exception_type",
        ):
            assert key in first_trace

    def test_simulate_engine_real_mpl_records(self) -> None:
        runner = CliRunner()
        res = runner.invoke(
            main,
            [
                "simulate",
                "--project",
                str(EXAMPLE_PROJECT),
                "--flow",
                "weather-logger-async",
                "--test",
                "smoke",
                "--engine",
                "real",
                "--json",
            ],
        )
        assert res.exit_code == 0, res.output
        data = json.loads(res.output)
        assert data["status"] == "COMPLETED"
        assert "mpl_records" in data
        assert len(data["mpl_records"]) == 1
        mpl = data["mpl_records"][0]
        assert mpl["Origin"] == "local-sim"
        assert mpl["Status"] == "COMPLETED"
        assert len(mpl["steps"]) >= 4

    def test_simulate_human_output_real_engine_prints_mpl(self) -> None:
        runner = CliRunner()
        res = runner.invoke(
            main,
            [
                "simulate",
                "--project",
                str(EXAMPLE_PROJECT),
                "--flow",
                "weather-logger-async",
                "--test",
                "smoke",
                "--engine",
                "real",
            ],
        )
        assert res.exit_code == 0, res.output
        assert "mpl records: 1 (Origin=local-sim)" in res.output

    def test_simulate_usage_error_missing_project(self) -> None:
        runner = CliRunner()
        res = runner.invoke(
            main,
            [
                "simulate",
                "--project",
                "/tmp/nonexistent_oiw_project_dir",
                "--flow",
                "flow",
            ],
        )
        assert res.exit_code == 2

    def test_simulate_usage_error_unknown_flow(self) -> None:
        runner = CliRunner()
        res = runner.invoke(
            main,
            [
                "simulate",
                "--project",
                str(EXAMPLE_PROJECT),
                "--flow",
                "nonexistent-flow-id",
            ],
        )
        assert res.exit_code == 2
        assert "flow 'nonexistent-flow-id' not found" in res.output

    def test_simulate_usage_error_unknown_test(self) -> None:
        runner = CliRunner()
        res = runner.invoke(
            main,
            [
                "simulate",
                "--project",
                str(EXAMPLE_PROJECT),
                "--flow",
                "weather-logger-async",
                "--test",
                "nonexistent-test",
            ],
        )
        assert res.exit_code == 2
        assert "test 'nonexistent-test' not found" in res.output
