"""Real-engine flag (P5a-M2): loud refusal of silent stubs + MPL records.

Blood rule (p5-p6-plan.md §0): "green locally" must never rest on a step
that only pretends to work. engine="real" refuses simulated-fidelity
NON-endpoint steps with the OIW-REAL-UNSUPPORTED marker; sender./receiver.*
stay mockable (world-dynamics seam, P5b).
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from click.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.cli import main  # noqa: E402
from oiw.project import Project  # noqa: E402
from oiw.testing import run_tests  # noqa: E402

HELD_OUT = REPO_ROOT / "examples" / "held-out-order-async"


def _write_mini_project(
    root: Path, *, nodes: list[dict] | None = None, body: str = "{}",
    expect_status: str = "COMPLETED",
) -> Path:
    """Smallest runnable project: sender.http -> log -> [*nodes] -> receiver.http (mocked)."""
    nodes = nodes or []
    flow_nodes = [
        {"id": "log-in", "type": "log.message", "config": {"message": "in"},
         "fidelity": "compatible-subset"}
    ] + nodes
    chain = ["sender-http"] + [n["id"] for n in flow_nodes] + ["receiver-out"]
    edges = [{"from": a, "to": b} for a, b in zip(chain, chain[1:], strict=False)]

    root.mkdir(parents=True, exist_ok=True)
    (root / "oiw.yaml").write_text(yaml.safe_dump({
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationProject",
        "metadata": {"id": "mini", "name": "mini", "created": "1970-01-01T00:00:00Z"},
        "spec": {"targetProfiles": ["sap-cloud-integration-2026-07"]},
    }))
    flow = {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationFlow",
        "metadata": {"id": "mini-flow", "name": "mini", "version": 1},
        "spec": {
            "entrypoints": [{
                "id": "sender-http", "type": "sender.http",
                "config": {"path": "/mini", "methods": ["POST"]},
            }],
            "nodes": flow_nodes,
            "edges": edges,
        },
    }
    (root / "flows" / "mini-flow").mkdir(parents=True)
    (root / "flows" / "mini-flow" / "flow.yaml").write_text(yaml.safe_dump(flow))
    (root / "flows" / "mini-flow" / "tests").mkdir()
    (root / "flows" / "mini-flow" / "tests" / "smoke.yaml").write_text(yaml.safe_dump({
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "FlowTest",
        "metadata": {"name": "smoke"},
        "spec": {
            "flow": "mini-flow",
            "input": {"entrypoint": "sender-http", "bodyInline": body},
            "mocks": [{"target": "receiver-out", "respond": {"status": 200, "body": "{}"}}],
            "assertions": [{"type": "exchange.status", "equals": expect_status}],
        },
    }))
    return root


def test_real_mode_passes_true_logic_chain():
    results = run_tests(Project.load(HELD_OUT), test_name="smoke", engine="real")
    assert len(results) == 1 and results[0].passed, results[0].failures
    r = results[0]
    assert r.real_engine_blocked is False
    assert r.mpl_records is not None
    assert r.mpl_records[0]["Origin"] == "local-sim"
    assert {s["StepId"] for s in r.mpl_records[0]["steps"]} >= {"log-receive", "receiver-out"}


def test_simulated_default_unchanged():
    results = run_tests(Project.load(HELD_OUT), test_name="smoke")
    assert results[0].passed
    assert results[0].mpl_records is None  # records are a real-mode artifact


def test_real_mode_refuses_stub_fidelity_loudly(tmp_path):
    proj = _write_mini_project(tmp_path / "stubbed", nodes=[
        {"id": "write-var", "type": "variables.write", "config": {"name": "v"}, "fidelity": "simulated"},
    ])
    results = run_tests(Project.load(proj), engine="real")
    r = results[0]
    assert not r.passed
    assert r.real_engine_blocked is True
    assert any("OIW-REAL-UNSUPPORTED" in f and "variables.write" in f for f in r.failures)


def test_real_mode_endpoint_steps_are_exempt():
    """receiver.* stays mockable in real mode (P5b seam) — held-out proves it."""
    results = run_tests(Project.load(HELD_OUT), test_name="smoke", engine="real")
    assert not results[0].real_engine_blocked


def test_cli_test_command_accepts_engine_flag():
    runner = CliRunner()
    res = runner.invoke(main, ["test", "--project", str(HELD_OUT), "--engine", "real", "--json"])
    assert res.exit_code == 0, res.output
    payload = __import__("json").loads(res.output)
    assert payload["engine"] == "real"
    assert payload["passed"] is True


def test_cli_test_rejects_unknown_engine():
    runner = CliRunner()
    res = runner.invoke(main, ["test", "--project", str(HELD_OUT), "--engine", "turbo"])
    assert res.exit_code != 0
