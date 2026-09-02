"""Turbo loop orchestrator — `oiw agent --turbo` (p5-p6-plan.md §5D).

plan → implement → simulate → repair cycles, no per-step approval
pauses, hard-bounded:

  Budgets (TurboBudget; the CLI maps flags onto them):
    - max_iterations: repair-cycle cap (default 3)
    - wall_clock_s: hard wall-clock cap (default 600)

  Tenant guard (CODE LEVEL, not convention): the turbo loop performs
  every mutation through `TurboToolGuard.dispatch`, which raises on any
  tenant-facing or LLM-facing tool namespace (tenant.*, deploy.*,
  gateway/llm chat) and on any tool outside the turbo allowlist. The
  native implementation behind the guard only touches the local project
  tree + local test engine. This is the seam a reviewer audits in one
  read: no adapter import, no HTTP client, no model gateway.

  LLM: NEVER the first mover. Turbo assembles from pieces + corpus. If
  assembly fails or repair exhausts the budget, it writes a structured
  teacher-request and stops — the teacher (a human or, later, an LLM
  teacher endpoint) must answer; the answer merges back as a new piece
  + regression case. TEACHER-SUMMONS RATE is the headline metric and
  must trend to zero.

  Trajectories: every turbo run records a full EngineeringTrajectory
  via TrajectoryRecorder — no silent runs.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..project import Project, ProjectError
from ..testing import run_tests
from ..validators.graph import validate_flow_graph
from .context import ProjectContext
from .interpreter import interpret_requirement_fallback
from .trajectory import TrajectoryRecorder
from .turbo_pieces import (
    AssemblyResult,
    Piece,
    assemble_from_requirement,
    assembly_to_flow,
)

# Tools turbo may dispatch. Everything else raises — most especially
# anything tenant-facing (deploy.*, tenant.*) and gateway/LLM calls.
_TURBO_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "flow.create",
        "flow.validate",
        "test.run",
        "test.create",
        "resource.write",
    }
)

_TENANT_TOOL_PREFIXES = ("tenant.", "deploy.")
_LLM_TOOLS = ("gateway.chat", "llm.chat", "agent.plan", "agent.interpret")


class TurboTenantError(RuntimeError):
    """Raised when turbo mode attempts to reach a tenant or LLM tool."""


class TurboToolGuard:
    """Code-level tenant + LLM guard for turbo mode.

    Every mutation the turbo loop performs goes through dispatch().
    The guard refuses entire tool namespaces that can touch the tenant
    or summon the teacher (LLM) prematurely — turbo is local-sim only;
    the human gate stays at PROPOSED→APPROVED for tenant interaction.
    """

    def __init__(self, dispatcher: Any | None = None):
        self._dispatcher = dispatcher
        self.refusals: list[str] = []

    def dispatch(self, tool: str, arguments: dict[str, Any]) -> Any:
        if tool.startswith(_TENANT_TOOL_PREFIXES) or tool in _LLM_TOOLS:
            self.refusals.append(tool)
            raise TurboTenantError(
                f"turbo mode: tool {tool!r} is tenant/LLM-facing and is "
                "refused at code level. Turbo is local-sim only; the human "
                "gate remains at PROPOSED→APPROVED for tenant interaction."
            )
        if tool not in _TURBO_ALLOWED_TOOLS:
            self.refusals.append(tool)
            raise TurboTenantError(
                f"turbo mode: tool {tool!r} is not on the turbo allowlist "
                f"({sorted(_TURBO_ALLOWED_TOOLS)})"
            )
        if self._dispatcher is None:
            return {"status": "applied", "applied": 0}
        return self._dispatcher(tool, arguments)


@dataclass
class TurboBudget:
    """Hard bounds for one turbo run."""

    max_iterations: int = 3
    wall_clock_s: float = 600.0

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if self.wall_clock_s <= 0:
            raise ValueError("wall_clock_s must be > 0")


@dataclass
class TeacherRequest:
    """Structured escalation — the only way turbo asks for help.

    Written to <project>/.oiw/teacher-requests/. A teacher (human or
    future LLM endpoint) answers; the answer MUST merge back as a new
    piece + regression case, or the summons rate will never trend down.
    """

    id: str
    requirement: str
    kind: str  # no-piece-matches | repair-exhausted | budget-exceeded
    unmatched_components: list[str] = field(default_factory=list)
    iterations_used: int = 0
    diagnostics: list[str] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "requirement": self.requirement,
            "kind": self.kind,
            "unmatchedComponents": self.unmatched_components,
            "iterationsUsed": self.iterations_used,
            "diagnostics": self.diagnostics,
            "createdAt": self.created_at,
        }


@dataclass
class TurboResult:
    """Outcome of one turbo run."""

    status: str  # COMPLETED | FAILED | TEACHER-REQUESTED | BUDGET-EXCEEDED
    flow_id: str | None = None
    trajectory_id: str = ""
    iterations_used: int = 0
    test_results: list[dict[str, Any]] = field(default_factory=list)
    teacher_request: TeacherRequest | None = None
    warnings: list[str] = field(default_factory=list)
    emg_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "flowId": self.flow_id,
            "trajectoryId": self.trajectory_id,
            "iterationsUsed": self.iterations_used,
            "testResults": self.test_results,
            "teacherRequest": self.teacher_request.to_dict() if self.teacher_request else None,
            "warnings": self.warnings,
            "emgUsed": self.emg_used,
        }


# ---------------------------------------------------------------------------
# Native tool implementations (local-only; called through the guard)
# ---------------------------------------------------------------------------


def _native_flow_create(args: dict[str, Any]) -> dict[str, Any]:
    """Create a flow dir + flow.yaml with entrypoints + nodes + edges.

    Unlike the MCP server's flow.create (which cannot carry entrypoint
    configs), the turbo-native version writes the full assembled IR.
    """
    project_root = Path(args["projectRoot"])
    flow_id = args["flowId"]
    flow_dir = project_root / "flows" / flow_id
    if flow_dir.exists():
        return {"error": f"flow '{flow_id}' already exists", "flowId": flow_id}
    flow_dir.mkdir(parents=True)

    flow_data = {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationFlow",
        "metadata": {
            "id": flow_id,
            "name": args.get("name", flow_id),
            "version": 1,
            "labels": {"archetype": "turbo-assembled"},
        },
        "spec": {
            "entrypoints": args.get("entrypoints", []),
            "nodes": args.get("nodes", []),
            "edges": args.get("edges", []),
            "extensions": {},
        },
    }
    (flow_dir / "flow.yaml").write_text(
        yaml.safe_dump(flow_data, sort_keys=True, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    (flow_dir / "tests").mkdir()
    return {"created": True, "flowId": flow_id}


def _native_flow_remove(args: dict[str, Any]) -> dict[str, Any]:
    """Remove a flow dir (repair iterations rebuild from scratch)."""
    import shutil

    project_root = Path(args["projectRoot"])
    flow_id = args["flowId"]
    flow_dir = project_root / "flows" / flow_id
    if flow_dir.is_dir():
        shutil.rmtree(flow_dir)
    return {"removed": True, "flowId": flow_id}


def _native_test_create(args: dict[str, Any]) -> dict[str, Any]:
    """Write a FlowTest YAML into the flow's tests dir."""
    project_root = Path(args["projectRoot"])
    path = project_root / args["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args["content"], encoding="utf-8")
    return {"created": True, "path": args["path"]}


def _native_flow_validate(args: dict[str, Any]) -> dict[str, Any]:
    """FULL validation (same engine as `oiw validate`): schema + graph + rules.

    Live finding (2026-09-02, P6 examples): turbo's earlier graph-only
    check let schema-invalid flows (underscore ids, missing test
    `input.entrypoint`) pass locally — the divergence surfaced only at
    `oiw validate` on the persisted example. Turbo now uses the complete
    chain so anything it ships is repo-valid.
    """
    project_root = Path(args["projectRoot"])
    try:
        project = Project.load(project_root)
    except ProjectError as exc:
        return {"error": str(exc), "errors": [str(exc)], "warnings": []}
    errors: list[str] = []
    warnings: list[str] = []
    from ..schema_validator import SchemaError, validate_project
    from ..validators.rules import run_rule_validators

    try:
        schema_results = validate_project(project)
        errors.extend(schema_results.errors)
        warnings.extend(schema_results.warnings)
    except SchemaError as exc:
        return {"error": str(exc), "errors": [str(exc)], "warnings": warnings}
    for flow in project.flows:
        if args.get("flowId") and flow.id != args["flowId"]:
            continue
        e, w = validate_flow_graph(flow)
        errors.extend(e)
        warnings.extend(w)
    rule_errors, rule_warnings = run_rule_validators(project)
    errors.extend(rule_errors)
    warnings.extend(rule_warnings)
    return {"errors": errors, "warnings": warnings}


def _native_test_run(args: dict[str, Any]) -> dict[str, Any]:
    """Run FlowTests via the canonical runner (simulated engine)."""
    project_root = Path(args["projectRoot"])
    try:
        project = Project.load(project_root)
    except ProjectError as exc:
        return {"error": str(exc), "passed": 0, "failed": 0, "results": []}
    results = run_tests(
        project,
        flow_id=args.get("flowId"),
        test_name=args.get("testName"),
        engine="simulated",
    )
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    return {
        "passed": passed,
        "failed": failed,
        "results": [
            {
                "flow": r.flow_id,
                "test": r.test_name,
                "passed": r.passed,
                "failures": r.failures,
            }
            for r in results
        ],
    }


def _turbo_dispatcher(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Native, local-only dispatcher the guard fronts."""
    if tool == "flow.create":
        return _native_flow_create(args)
    if tool == "flow.remove":
        return _native_flow_remove(args)
    if tool == "test.create":
        return _native_test_create(args)
    if tool == "flow.validate":
        return _native_flow_validate(args)
    if tool == "test.run":
        return _native_test_run(args)
    return {"error": f"turbo has no native implementation for {tool!r}"}


# flow.remove is a turbo-internal repair verb (local tree only).
_TURBO_ALLOWED_TOOLS = _TURBO_ALLOWED_TOOLS | {"flow.remove"}


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def _smoke_test_yaml(
    flow_id: str,
    node_ids: list[str],
    entrypoint_id: str = "sender-main",
    body: str = "{}",
    content_type: str = "application/json",
) -> dict[str, Any]:
    """Deterministic smoke FlowTest for an assembled flow.

    Asserts the exchange completes and every assembled node executed —
    the minimum bar a "functional iFlow" must clear in the simulated
    world before it deserves repair-loop attention.
    """
    assertions: list[dict[str, Any]] = [
        {"type": "exchange.status", "equals": "COMPLETED"},
        *[{"type": "node.executed", "node": nid} for nid in node_ids],
    ]
    return {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "FlowTest",
        "metadata": {
            "name": f"turbo-smoke-{flow_id}",
            "description": "Deterministic turbo smoke test (auto-generated).",
        },
        "spec": {
            "flow": flow_id,
            "input": {
                "entrypoint": entrypoint_id,
                "bodyInline": body,
                "headers": {"Content-Type": content_type},
            },
            "assertions": assertions,
            "mocks": [
                {
                    "target": "receiver-out",
                    "respond": {"status": 200, "body": ""},
                },
                {
                    # Converter-law warmup RR (assembler-inserted when
                    # converting the inbound body): give it a JSON body
                    # so downstream converters have valid input locally.
                    "target": "step-rr-warmup",
                    "respond": {"status": 200, "body": '{"warmup": true}'},
                },
            ],
        },
    }


def _flow_native_spec(flow: Any) -> dict[str, Any]:
    """Serialize an assembled IntegrationFlow for _native_flow_create."""
    return {
        "entrypoints": [
            {
                "id": e.id,
                "type": e.type,
                "config": e.config,
                "fidelity": e.fidelity,
            }
            for e in flow.entrypoints
        ],
        "nodes": [
            {"id": n.id, "type": n.type, "config": n.config, "fidelity": n.fidelity} for n in flow.nodes
        ],
        "edges": [
            {"from": e.from_, "to": e.to, **({"condition": e.condition} if e.condition else {})}
            for e in flow.edges
        ],
    }


def _digest(obj: Any) -> str:
    canonical = yaml.safe_dump(obj, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _record(
    recorder: TrajectoryRecorder,
    step_index: int,
    action_type: str,
    normalized: tuple[str, ...],
    args: dict[str, Any],
    status: str,
    summary: str,
) -> None:
    recorder.record_action(
        step_index=step_index,
        action_type=action_type,
        normalized=tuple(str(x) for x in normalized),
        arguments_digest=_digest({k: args.get(k) for k in sorted(args)}),
        result_status=status,
        result_summary=summary,
    )


async def run_turbo(
    requirement: str,
    project_path: Path,
    *,
    flow_id: str | None = None,
    budget: TurboBudget | None = None,
    emg_retriever: Any = None,
    persist_dir: Path | str | None = None,
) -> TurboResult:
    """Run the bounded, LLM-free, tenant-isolated turbo loop.

    Pipeline per iteration:
      1. interpret (deterministic fallback interpreter — NO LLM)
      2. EMG mechanics-first retrieval (inject expert workflow if hit)
      3. assemble pieces (grammar + corpus only; never freeform)
      4. write flow + smoke test (guarded, local tree only)
      5. validate (same engine as `oiw validate`)
      6. run smoke test (simulated engine — world mocks seam)
      7. green → COMPLETED; else repair (drop last piece) and retry

    Terminal states: COMPLETED | TEACHER-REQUESTED | BUDGET-EXCEEDED.
    """
    budget = budget or TurboBudget()
    guard = TurboToolGuard(_turbo_dispatcher)
    flow_id = flow_id or f"turbo-{uuid.uuid4().hex[:8]}"
    # IR schema: flow ids are kebab-case (^[a-z0-9][a-z0-9-]{0,62}$).
    # Sanitize deterministically so anything turbo ships validates.
    flow_id = re.sub(r"[^a-z0-9-]+", "-", flow_id.lower()).strip("-") or (f"turbo-{uuid.uuid4().hex[:8]}")
    deadline = time.monotonic() + budget.wall_clock_s

    result = TurboResult(status="FAILED", flow_id=flow_id)
    warnings: list[str] = []

    project_context = ProjectContext.load(project_path)
    recorder = TrajectoryRecorder(
        project_id=project_context.project_id,
        task_id=f"turbo-{uuid.uuid4().hex[:8]}",
        base_revision=project_context.git_head(),
        persist_dir=persist_dir or (project_context.root / ".oiw" / "trajectories"),
    )

    iteration = 0
    diagnostics: list[str] = []
    assembly: AssemblyResult | None = None
    normalized = interpret_requirement_fallback(requirement)
    recorder.set_query(requirement, normalized)
    used_flow_id = flow_id

    # --- EMG mechanics-first (once, before iteration loop) ---------------
    if emg_retriever is not None:
        retrieval = emg_retriever.retrieve(
            requirement=normalized,
            project_id=project_context.project_id,
        )
        if retrieval.found and retrieval.insight is not None:
            from ..emg.retrieval import inject_insight_into_plan

            injected = inject_insight_into_plan(
                insight=retrieval.insight,
                base_revision=project_context.git_head(),
                project_id=project_context.project_id,
                flow_id=flow_id,
            )
            if injected:
                emg_assembly = _assembly_from_injection(injected)
                if emg_assembly is not None and _injection_is_shippable(emg_assembly):
                    assembly = emg_assembly
                    result.emg_used = True
                    warnings.append(
                        f"OIW-I001: EMG insight retrieved (confidence="
                        f"{retrieval.confidence:.2f}); using expert workflow "
                        "instead of piece assembly"
                    )
                elif emg_assembly is not None:
                    # Expert chain references piece types we cannot ship
                    # (xslt mappings, subprocesses, unclassified steps) —
                    # fall through to piece assembly rather than shipping
                    # an unrenderable chain (honesty floor, 2026-09-02).
                    warnings.append(
                        f"OIW-I002: EMG insight retrieved (confidence="
                        f"{retrieval.confidence:.2f}) but its workflow contains "
                        "non-piece steps; falling back to piece assembly"
                    )

    while iteration < budget.max_iterations and time.monotonic() < deadline:
        iteration += 1
        step_idx = iteration * 10  # spaced indices per iteration for trajectory

        recorder.record_observation(
            step_index=step_idx,
            obs_type="turbo.iteration-start",
            state={"iteration": iteration, "flowId": used_flow_id},
        )

        # 3. Assemble from pieces (if EMG did not provide a workflow).
        if assembly is None:
            assembly = assemble_from_requirement(normalized, used_flow_id)

        if assembly.entrypoint is None or assembly.receiver is None:
            diagnostics.append(assembly.reason)
            _record(
                recorder,
                step_idx,
                "flow.assemble",
                ("flow.assemble", "assemble", "pieces"),
                {"reason": assembly.reason},
                "failed",
                assembly.reason,
            )
            break  # cannot assemble — teacher territory

        # Honesty rule: unmatched components are NOT silently dropped.
        # A requirement the piece library cannot satisfy is a teacher
        # request, never a pretend-completed flow missing functionality.
        if assembly.unmatched_components:
            diagnostics.append("no proven piece for: " + ", ".join(assembly.unmatched_components))
            _record(
                recorder,
                step_idx,
                "flow.assemble",
                ("flow.assemble", "assemble", "pieces"),
                {"unmatched": assembly.unmatched_components},
                "failed",
                f"no proven piece for {', '.join(assembly.unmatched_components)}",
            )
            break  # teacher territory

        # 4. (Re)create the flow. The remove-then-create pair runs EVERY
        # iteration — turbo runs must be idempotent over an existing
        # project tree (re-running a directive refreshes the flow).
        guard.dispatch(
            "flow.remove",
            {
                "projectRoot": str(project_context.root),
                "flowId": used_flow_id,
            },
        )
        flow = assembly_to_flow(assembly, used_flow_id)
        spec = _flow_native_spec(flow)

        # Companion listener (live topology law 2026-09-02): RR chains end
        # via ProcessDirect; the PD hop needs a listener on the other side.
        # Written in the same iteration as the main flow so the pair stays
        # in sync (proven multi-artifact choreography, session 5).
        listener_written = False
        if assembly.companion_listener_address:
            from .turbo_pieces import companion_listener_flow

            listener_id = f"{used_flow_id}-listener"
            listener = companion_listener_flow(assembly.companion_listener_address, listener_id)
            guard.dispatch(
                "flow.remove",
                {"projectRoot": str(project_context.root), "flowId": listener_id},
            )
            lc = guard.dispatch(
                "flow.create",
                {
                    "projectRoot": str(project_context.root),
                    "flowId": listener_id,
                    "name": listener.name,
                    **_flow_native_spec(listener),
                },
            )
            listener_written = isinstance(lc, dict) and not lc.get("error")
            if not listener_written:
                diagnostics.append(
                    f"listener create failed: {lc.get('error') if isinstance(lc, dict) else lc}"
                )

        cr = guard.dispatch(
            "flow.create",
            {
                "projectRoot": str(project_context.root),
                "flowId": used_flow_id,
                "name": flow.name,
                **spec,
            },
        )
        if isinstance(cr, dict) and cr.get("error"):
            diagnostics.append(f"flow.create failed: {cr['error']}")
            _record(
                recorder,
                step_idx + 1,
                "flow.create",
                ("flow.create", "create", used_flow_id),
                {"flowId": used_flow_id},
                "failed",
                str(cr["error"]),
            )
            break
        _record(
            recorder,
            step_idx + 1,
            "flow.create",
            ("flow.create", "create", used_flow_id),
            {"flowId": used_flow_id, "nodes": len(spec["nodes"])},
            "applied",
            f"created flow with {len(spec['nodes'])} nodes",
        )

        # Smoke test: every assembled node must execute.
        node_ids = [p.node_id for p in assembly.pieces] + [assembly.receiver.node_id]
        test_payload = _smoke_test_yaml(used_flow_id, node_ids, entrypoint_id=assembly.entrypoint.node_id)
        # The PD companion listener gets its own smoke test (PD sender →
        # log terminal; conv9 law — variables.write rides PD as headers
        # and rejects multi-line payloads).
        if listener_written:
            ltest = _smoke_test_yaml(
                f"{used_flow_id}-listener",
                ["log-receive"],
                entrypoint_id="pd-in",
                body='{"ping": true}',
                content_type="application/json",
            )
            ltest["metadata"]["name"] = f"turbo-smoke-{used_flow_id}-listener"
            ltest["metadata"]["description"] = "Companion PD listener smoke test (auto-generated)."
            ltest["spec"]["mocks"] = []
            lw = guard.dispatch(
                "test.create",
                {
                    "projectRoot": str(project_context.root),
                    "path": f"flows/{used_flow_id}-listener/tests/turbo-smoke.yaml",
                    "content": yaml.safe_dump(ltest, sort_keys=True),
                },
            )
            if isinstance(lw, dict) and lw.get("error"):
                diagnostics.append(f"listener test write failed: {lw['error']}")
        tw = guard.dispatch(
            "test.create",
            {
                "projectRoot": str(project_context.root),
                "path": f"flows/{used_flow_id}/tests/turbo-smoke.yaml",
                "content": yaml.safe_dump(test_payload, sort_keys=True),
            },
        )
        if isinstance(tw, dict) and tw.get("error"):
            diagnostics.append(f"test write failed: {tw['error']}")

        # 5. Validate.
        vr = guard.dispatch(
            "flow.validate",
            {
                "projectRoot": str(project_context.root),
                "flowId": used_flow_id,
            },
        )
        v_errors = vr.get("errors", []) if isinstance(vr, dict) else ["non-dict result"]
        if isinstance(vr, dict) and vr.get("error"):
            v_errors = [vr["error"]]
        if v_errors:
            summary = "; ".join(v_errors[:3])
            diagnostics.append(f"validation failed: {summary}")
            _record(
                recorder,
                step_idx + 2,
                "flow.validate",
                ("flow.validate", "validate", used_flow_id),
                {"flowId": used_flow_id},
                "failed",
                summary,
            )
            repaired = _repair_assembly(assembly, summary)
            if repaired is None:
                break
            assembly = repaired
            continue
        _record(
            recorder,
            step_idx + 2,
            "flow.validate",
            ("flow.validate", "validate", used_flow_id),
            {"flowId": used_flow_id},
            "applied",
            f"errors=0 warnings={len(vr.get('warnings', []))}",
        )

        # 6. Run the smoke test.
        tr = guard.dispatch(
            "test.run",
            {
                "projectRoot": str(project_context.root),
                "flowId": used_flow_id,
                "testName": f"turbo-smoke-{used_flow_id}",
            },
        )
        if isinstance(tr, dict) and tr.get("error"):
            diagnostics.append(f"test run failed: {tr['error']}")
            _record(
                recorder,
                step_idx + 3,
                "test.run",
                ("test.run", "run", used_flow_id),
                {"flowId": used_flow_id},
                "failed",
                str(tr["error"]),
            )
            repaired = _repair_assembly(assembly, str(tr["error"]))
            if repaired is None:
                break
            assembly = repaired
            continue

        passed = int(tr.get("passed", 0))
        failed = int(tr.get("failed", 0))
        result.test_results = [
            {
                "iteration": iteration,
                "passed": passed,
                "failed": failed,
                "results": tr.get("results", []),
            }
        ]
        if failed == 0 and passed > 0:
            _record(
                recorder,
                step_idx + 3,
                "test.run",
                ("test.run", "run", used_flow_id),
                {"flowId": used_flow_id},
                "applied",
                f"passed={passed} failed={failed}",
            )
            recorder.finalize(
                "success",
                {
                    "completion": 1.0,
                    "iterations": iteration,
                    "emgUsed": result.emg_used,
                    "testPassRate": 1.0,
                },
            )
            result.status = "COMPLETED"
            result.iterations_used = iteration
            result.warnings = warnings
            result.trajectory_id = recorder.trajectory_id
            return result

        failure_detail = "; ".join(
            f"{r['test']}: {' | '.join(r.get('failures', [])[:2])}"
            for r in tr.get("results", [])
            if not r.get("passed")
        )[:300]
        diagnostics.append(f"tests failed (iter {iteration}): {failure_detail}")
        _record(
            recorder,
            step_idx + 3,
            "test.run",
            ("test.run", "run", used_flow_id),
            {"flowId": used_flow_id},
            "failed",
            failure_detail or "no tests ran",
        )
        repaired = _repair_assembly(assembly, failure_detail)
        if repaired is None:
            break
        assembly = repaired
    else:
        # while-condition exhausted (iterations or deadline) — fall through
        # to terminal handling below.
        pass

    # --- Terminal handling ------------------------------------------------
    if time.monotonic() >= deadline:
        result.status = "BUDGET-EXCEEDED"
        kind = "budget-exceeded"
    else:
        result.status = "TEACHER-REQUESTED"
        kind = (
            "no-piece-matches"
            if assembly is not None and assembly.unmatched_components
            else "repair-exhausted"
        )
        if assembly is None:
            kind = "no-piece-matches"

    req = TeacherRequest(
        id=f"teacher-{uuid.uuid4().hex[:10]}",
        requirement=requirement,
        kind=kind,
        unmatched_components=(assembly.unmatched_components if assembly else []),
        iterations_used=iteration,
        diagnostics=diagnostics,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    _persist_teacher_request(project_context.root, req)
    result.teacher_request = req
    result.iterations_used = iteration
    result.warnings = warnings
    result.trajectory_id = recorder.trajectory_id
    recorder.finalize(
        "failed",
        {
            "completion": 0.0,
            "iterations": iteration,
            "teacherRequest": req.id,
        },
    )
    return result


def _injection_is_shippable(assembly: AssemblyResult) -> bool:
    """True when every EMG-injected step maps to a current piece-library type.

    Absorbed tenant chains carry steps we cannot render yet (xslt
    mappings need script resources, subprocess.local needs subprocess
    rendering, 'ServiceTask' entries are unclassified RRs). Shipping one
    would deploy a bundle the exporter refuses — fall back to pieces
    instead (live finding 2026-09-02, turbo-conv run).
    """
    from .turbo_pieces import proven_pieces

    shippable = set(proven_pieces())
    chain_types = [p.node_type for p in assembly.pieces]
    entry_ok = assembly.entrypoint is not None and (
        assembly.entrypoint.node_type.startswith(("sender.", "receiver."))
        or assembly.entrypoint.node_type in shippable
    )
    recv_ok = assembly.receiver is not None and (
        assembly.receiver.node_type.startswith(("sender.", "receiver."))
        or assembly.receiver.node_type in shippable
    )
    return entry_ok and recv_ok and all(t in shippable for t in chain_types)


def _assembly_from_injection(
    injected: list[dict[str, Any]],
) -> AssemblyResult | None:
    """Convert EMG-injected steps into an AssemblyResult, if possible.

    The injected steps are flow.patch addNode ops; the assembler needs
    an entrypoint + terminal receiver pair to build a runnable flow.
    If the expert workflow carries both, we mirror it verbatim;
    otherwise fall back to piece assembly.
    """
    entry: Piece | None = None
    receiver: Piece | None = None
    chain: list[Piece] = []
    for i, step in enumerate(injected):
        ops = (step.get("arguments") or {}).get("operations") or []
        for op in ops:
            if op.get("op") != "addNode":
                continue
            node = op.get("node") or {}
            ntype = node.get("type", "")
            if ntype.startswith("sender.") and entry is None:
                entry = Piece(
                    node_id=node.get("id", "sender-main"),
                    node_type=ntype,
                    config=node.get("config", {}) or {},
                    fidelity=node.get("fidelity", "simulated"),
                    rationale="EMG-injected entrypoint",
                )
            elif ntype.startswith("receiver.") and receiver is None:
                receiver = Piece(
                    node_id=node.get("id", "receiver-out"),
                    node_type=ntype,
                    config=node.get("config", {}) or {},
                    fidelity=node.get("fidelity", "simulated"),
                    rationale="EMG-injected receiver",
                )
            else:
                chain.append(
                    Piece(
                        node_id=node.get("id", f"emg-step-{i}"),
                        node_type=ntype,
                        config=node.get("config", {}) or {},
                        fidelity=node.get("fidelity", "compatible-subset"),
                        rationale="EMG-injected piece",
                    )
                )
    if entry is None or receiver is None:
        return None
    return AssemblyResult(
        assembled=True,
        pieces=chain,
        unmatched_components=[],
        entrypoint=entry,
        receiver=receiver,
        reason="EMG-injected expert workflow",
    )


def _repair_assembly(
    assembly: AssemblyResult,
    failure_summary: str,
) -> AssemblyResult | None:
    """One deterministic repair move: drop the last internal piece.

    Deliberately minimal — the piece-assembler's repair space is
    "fewer pieces", not "different pieces". If a piece is genuinely
    needed but broken, repair cannot fix it; that is a teacher request.
    Returns None when the chain is empty (nothing left to drop).
    """
    if not assembly.pieces:
        return None
    return AssemblyResult(
        assembled=True,
        pieces=assembly.pieces[:-1],
        unmatched_components=assembly.unmatched_components,
        entrypoint=assembly.entrypoint,
        receiver=assembly.receiver,
        reason=f"repaired after: {failure_summary[:120]}",
    )


def _persist_teacher_request(project_root: Path, req: TeacherRequest) -> Path:
    out_dir = Path(project_root) / ".oiw" / "teacher-requests"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{req.id}.yaml"
    path.write_text(yaml.safe_dump(req.to_dict(), sort_keys=False), encoding="utf-8")
    return path


def teacher_summons_rate(project_root: Path) -> dict[str, Any]:
    """Headline self-improvement metric for one project root.

    teacher-summons rate = teacher requests / turbo trajectories. It
    MUST trend to zero as the piece library + corpus grow. Published by
    `oiw agent turbo-stats`.
    """
    traj_dir = Path(project_root) / ".oiw" / "trajectories"
    req_dir = Path(project_root) / ".oiw" / "teacher-requests"
    runs = len(list(traj_dir.glob("*.yaml"))) if traj_dir.is_dir() else 0
    summons = len(list(req_dir.glob("*.yaml"))) if req_dir.is_dir() else 0
    return {
        "turboRuns": runs,
        "teacherSummons": summons,
        "teacherSummonsRate": round(summons / runs, 4) if runs else None,
        "note": "teacher-summons rate must trend to zero as pieces + corpus grow",
    }


__all__ = [
    "run_turbo",
    "TurboResult",
    "TurboBudget",
    "TurboToolGuard",
    "TurboTenantError",
    "TeacherRequest",
    "teacher_summons_rate",
]
