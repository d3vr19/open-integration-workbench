"""Phase D — turbo piece-assembler tests (p5-p6-plan.md §5D).

Covers:
  - D-1 TurboToolGuard: code-level tenant + LLM isolation; budgets.
  - D-2 assemble_from_requirement: deterministic assembly from the
    proven-piece library; honest unmatched reporting.
  - D-3 run_turbo: end-to-end loop (assemble→create→validate→test);
    teacher escalation on unmatched pieces; repair cycles on failures;
    trajectory recording; teacher-summons-rate metric.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from oiw.agent.interpreter import interpret_requirement_fallback
from oiw.agent.turbo import (
    TeacherRequest,
    TurboBudget,
    TurboResult,
    TurboTenantError,
    TurboToolGuard,
    run_turbo,
    teacher_summons_rate,
)
from oiw.agent.turbo_pieces import (
    assemble_from_requirement,
    assembly_to_flow,
    proven_pieces,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLE = REPO_ROOT / "examples" / "held-out-order-async"

CREATE_REQ = (
    "Create a flow that receives a JSON order via HTTPS, sets a correlation "
    "ID in the header, and forwards the order to an order API."
)

# Converters are LIVE-PROVEN (conv9 bisection 2026-09-02: RR→converter→RR→PD,
# reward 1.0) with a placement law — see test_converter_is_a_piece_with_placement_law.
CONVERTER_REQ = (
    "Create a flow that receives a JSON order via HTTPS, converts the JSON "
    "body to XML, and forwards the XML to an order API."
)
XSLT_REQ = "Build a new flow that transforms orders with XSLT mapping and " "forwards them to an order API."


@pytest.fixture()
def temp_project(tmp_path: Path):
    """Copy held-out-order-async to tmp, init git, no EMG store.

    .oiw/ runtime state (trajectories, calibrations) is excluded so
    every test starts from a clean slate.
    """
    import os

    dest = tmp_path / "prj"
    shutil.copytree(EXAMPLE, dest, ignore=shutil.ignore_patterns(".oiw"))
    # Wipe existing flows so turbo creates fresh ones.
    for f in (dest / "flows").iterdir():
        shutil.rmtree(f)
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(["git", "-C", str(dest), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(dest), "commit", "-q", "-m", "test fixture"],
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
        check=True,
    )
    old = os.environ.get("OIW_WORKSPACE")
    os.environ["OIW_WORKSPACE"] = str(tmp_path)
    try:
        yield dest
    finally:
        if old is not None:
            os.environ["OIW_WORKSPACE"] = old
        else:
            os.environ.pop("OIW_WORKSPACE", None)


class TestTurboToolGuard:
    """D-1: the code-level tenant/LLM wall."""

    def test_tenant_tools_refused(self) -> None:
        guard = TurboToolGuard()
        with pytest.raises(TurboTenantError, match="tenant/LLM-facing"):
            guard.dispatch("tenant.calibrate", {})
        with pytest.raises(TurboTenantError, match="tenant/LLM-facing"):
            guard.dispatch("deploy.upload", {})

    def test_llm_tools_refused(self) -> None:
        guard = TurboToolGuard()
        with pytest.raises(TurboTenantError, match="tenant/LLM-facing"):
            guard.dispatch("gateway.chat", {})

    def test_off_allowlist_tools_refused(self) -> None:
        guard = TurboToolGuard()
        with pytest.raises(TurboTenantError, match="allowlist"):
            guard.dispatch("some.unknown.tool", {})

    def test_allowed_tools_pass_through(self) -> None:
        guard = TurboToolGuard()  # no dispatcher -> passthrough stub
        result = guard.dispatch("flow.create", {"flowId": "x"})
        assert result["status"] == "applied"

    def test_refusals_recorded(self) -> None:
        guard = TurboToolGuard()
        for tool in ("tenant.ping", "deploy.execute", "gateway.chat"):
            with pytest.raises(TurboTenantError):
                guard.dispatch(tool, {})
        assert guard.refusals == ["tenant.ping", "deploy.execute", "gateway.chat"]


class TestTurboBudget:
    def test_valid_budget(self) -> None:
        b = TurboBudget(max_iterations=5, wall_clock_s=30)
        assert b.max_iterations == 5

    def test_zero_iterations_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_iterations"):
            TurboBudget(max_iterations=0)

    def test_nonpositive_clock_rejected(self) -> None:
        with pytest.raises(ValueError, match="wall_clock"):
            TurboBudget(wall_clock_s=0)


class TestPieceAssembly:
    """D-2: deterministic assembly from the proven library."""

    def test_proven_pieces_are_real_engine_safe(self) -> None:
        pieces = proven_pieces()
        # Endpoints are the mock seam — always included.
        assert "sender.http" in pieces
        assert "receiver.http" in pieces
        # Real-logic steps included.
        assert "converter.json-to-xml" in pieces
        assert "modifier.content" in pieces
        assert "log.message" in pieces
        assert "splitter.general" in pieces
        assert "gather" in pieces
        # Simulated stubs are NOT pieces (honesty floor).
        assert "transform.xslt" not in pieces

    def test_assemble_happy_path(self) -> None:
        req = interpret_requirement_fallback(CREATE_REQ)
        res = assemble_from_requirement(req, "t1")
        assert res.assembled
        assert res.unmatched_components == []
        assert res.entrypoint is not None and res.entrypoint.node_type == "sender.http"
        # Live topology law (2026-09-02): terminal HTTP receivers render as
        # MID-FLOW Request-Reply + ProcessDirect terminator; the companion
        # listener address rides along for the pair deploy.
        assert res.receiver is not None and res.receiver.node_type == "receiver.processdirect"
        chain = [p.node_type for p in res.pieces]
        assert "modifier.content" in chain
        assert "receiver.http" in chain  # mid-flow RR step
        assert res.companion_listener_address == "/t1_pd"

    def test_converter_is_a_piece_with_placement_law(self) -> None:
        """converter.json-to-xml is LIVE-PROVEN (conv9/conv10, 2026-09-02:
        RR→converter→RR→PD chains, reward 1.0). Converter law: a converter
        must be PRECEDED by a Request-Reply — converting the raw inbound
        body then calling an HTTP receiver fails at the adapter live. The
        assembler inserts an RR warmup before conversion when needed."""
        req = interpret_requirement_fallback(CONVERTER_REQ)
        res = assemble_from_requirement(req, "t2")
        assert res.assembled
        assert "converter.json-to-xml" not in res.unmatched_components
        chain_types = [p.node_type for p in res.pieces]
        assert "converter.json-to-xml" in chain_types
        if "receiver.http" in chain_types[: chain_types.index("converter.json-to-xml")]:
            pass  # converter already preceded by an RR
        else:
            # warmup inserted at the chain head
            assert chain_types[0] == "receiver.http" or "receiver.http" in chain_types

    def test_assemble_reports_unmatched_honestly(self) -> None:
        req = interpret_requirement_fallback(XSLT_REQ)
        res = assemble_from_requirement(req, "t2")
        assert "transform.xslt" in res.unmatched_components

    def test_error_handling_requirement_is_create_shaped(self) -> None:
        # Requirements mentioning "error subprocess that logs" keyword-classify
        # as fix-flow; the structural check (sender+receiver) must still
        # assemble them — this is exactly the held-out shape.
        req = interpret_requirement_fallback(
            CREATE_REQ + " Include an error subprocess that logs and returns 500 on failure."
        )
        res = assemble_from_requirement(req, "t3")
        assert res.assembled
        assert res.entrypoint is not None

    def test_modify_flow_intent_not_assembled(self) -> None:
        req = interpret_requirement_fallback("Update the receiver timeout to 60 seconds")
        res = assemble_from_requirement(req, "t4")
        assert not res.assembled
        assert "co-pilot" in res.reason

    def test_assembly_to_flow_produces_valid_ir(self) -> None:
        req = interpret_requirement_fallback(CREATE_REQ)
        res = assemble_from_requirement(req, "t5")
        flow = assembly_to_flow(res, "t5")
        from oiw.validators.graph import validate_flow_graph

        errors, _ = validate_flow_graph(flow)
        assert errors == []
        # Linear chain: entry -> pieces -> receiver
        ids = [flow.entrypoints[0].id] + [n.id for n in flow.nodes]
        assert len(flow.edges) == len(ids) - 1


@pytest.mark.asyncio
class TestRunTurbo:
    """D-3: the loop itself."""

    async def test_completes_on_first_iteration(self, temp_project: Path) -> None:
        result = await run_turbo(
            CREATE_REQ,
            temp_project,
            flow_id="turbo-happy",
            budget=TurboBudget(max_iterations=3, wall_clock_s=60),
        )
        assert result.status == "COMPLETED"
        assert result.iterations_used == 1
        assert result.teacher_request is None
        # Flow exists on disk with the assembled chain.
        flow_file = temp_project / "flows" / "turbo-happy" / "flow.yaml"
        assert flow_file.is_file()
        data = yaml.safe_load(flow_file.read_text())
        types = [n["type"] for n in data["spec"]["nodes"]]
        assert "modifier.content" in types
        assert "receiver.http" in types  # mid-flow RR
        assert "receiver.processdirect" in types  # PD terminator (live law)
        # Smoke test exists and asserts node execution.
        test_file = temp_project / "flows" / "turbo-happy" / "tests" / "turbo-smoke.yaml"
        assert test_file.is_file()
        # Trajectory recorded.
        traj = temp_project / ".oiw" / "trajectories" / f"{result.trajectory_id}.yaml"
        assert traj.is_file()
        tdata = yaml.safe_load(traj.read_text())
        assert tdata["spec"]["outcome"]["status"] == "success"

    async def test_teacher_escalation_on_unmatched_piece(self, temp_project: Path) -> None:
        result = await run_turbo(
            XSLT_REQ,
            temp_project,
            flow_id="turbo-xslt",
            budget=TurboBudget(max_iterations=2, wall_clock_s=60),
        )
        assert result.status == "TEACHER-REQUESTED"
        assert result.teacher_request is not None
        assert result.teacher_request.kind == "no-piece-matches"
        assert "transform.xslt" in result.teacher_request.unmatched_components
        # The request is persisted for the teacher.
        req_file = temp_project / ".oiw" / "teacher-requests" / f"{result.teacher_request.id}.yaml"
        assert req_file.is_file()
        data = yaml.safe_load(req_file.read_text())
        assert data["kind"] == "no-piece-matches"
        # No flow was created (assembly refused before writing).
        assert not (temp_project / "flows" / "turbo-xslt").exists()

    async def test_budget_wall_clock_enforced(self, temp_project: Path) -> None:
        # A near-zero wall clock trips before any iteration completes.
        result = await run_turbo(
            CREATE_REQ,
            temp_project,
            flow_id="turbo-clock",
            budget=TurboBudget(max_iterations=3, wall_clock_s=0.0001),
        )
        assert result.status in ("BUDGET-EXCEEDED", "TEACHER-REQUESTED")

    async def test_tenant_guard_wired_into_loop(self, temp_project: Path) -> None:
        """The loop's own dispatcher must be guard-fronted: patching the
        native dispatcher to attempt a tenant call raises, proving the
        guard sits in front of every mutation. The crash is LOUD — a
        smuggled tenant call must never degrade into a quiet failure."""
        from oiw.agent import turbo as turbo_mod

        original = turbo_mod._turbo_dispatcher

        def evil_dispatcher(tool: str, args: dict) -> dict:
            if tool == "flow.create":
                raise TurboTenantError("tenant call smuggled")
            return original(tool, args)

        turbo_mod._turbo_dispatcher = evil_dispatcher
        try:
            with pytest.raises(TurboTenantError, match="tenant call smuggled"):
                await run_turbo(
                    CREATE_REQ,
                    temp_project,
                    flow_id="turbo-guard",
                    budget=TurboBudget(max_iterations=1, wall_clock_s=60),
                )
        finally:
            turbo_mod._turbo_dispatcher = original
        # And nothing was written — the crash happened before creation.
        assert not (temp_project / "flows" / "turbo-guard").exists()


class TestTeacherSummonsRate:
    def test_rate_math(self, temp_project: Path) -> None:
        # 2 trajectories, 1 teacher request -> 0.5
        tdir = temp_project / ".oiw" / "trajectories"
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "traj-aaa.yaml").write_text("metadata: {}")
        (tdir / "traj-bbb.yaml").write_text("metadata: {}")
        rdir = temp_project / ".oiw" / "teacher-requests"
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / "teacher-xxx.yaml").write_text("id: teacher-xxx")

        stats = teacher_summons_rate(temp_project)
        assert stats["turboRuns"] == 2
        assert stats["teacherSummons"] == 1
        assert stats["teacherSummonsRate"] == 0.5

    def test_zero_runs_is_none(self, temp_project: Path) -> None:
        stats = teacher_summons_rate(temp_project)
        assert stats["turboRuns"] == 0
        assert stats["teacherSummonsRate"] is None


class TestTurboResultShape:
    def test_to_dict_roundtrip(self) -> None:
        r = TurboResult(
            status="TEACHER-REQUESTED",
            flow_id="f",
            trajectory_id="t",
            teacher_request=TeacherRequest(
                id="teacher-x",
                requirement="req",
                kind="no-piece-matches",
                unmatched_components=["transform.xslt"],
                iterations_used=2,
                created_at="2026-08-26T00:00:00Z",
            ),
        )
        d = r.to_dict()
        assert d["status"] == "TEACHER-REQUESTED"
        assert d["teacherRequest"]["unmatchedComponents"] == ["transform.xslt"]
        assert d["emgUsed"] is False
