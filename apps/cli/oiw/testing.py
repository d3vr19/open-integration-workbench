"""FlowTest runner.

Spec ref: §7.4 (FlowTest IR), §17 (testing strategy).
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

from .project import FlowTest, Project
from .runtime.engine import REAL_UNSUPPORTED_MARKER, ExecutionError, execute_flow
from .runtime.mpl import mpl_records_from_context


@dataclasses.dataclass
class TestResult:
    flow_id: str
    test_name: str
    passed: bool
    duration_ms: int
    failures: list[str] = dataclasses.field(default_factory=list)
    # P5a-M2 (--engine real): MPL-shaped local records + refusal marker.
    mpl_records: list[dict[str, Any]] | None = None
    real_engine_blocked: bool = False


def run_tests(
    project: Project,
    flow_id: str | None = None,
    test_name: str | None = None,
    engine: str = "simulated",
) -> list[TestResult]:
    results: list[TestResult] = []
    for test in project.tests:
        if flow_id and test.flow != flow_id:
            continue
        if test_name and test.name != test_name:
            continue
        results.append(_run_one(project, test, engine=engine))
    return results


def _run_one(project: Project, test: FlowTest, engine: str = "simulated") -> TestResult:
    start = time.monotonic()
    flow = None
    try:
        flow = project.get_flow(test.flow)
    except Exception as exc:
        return TestResult(
            flow_id=test.flow,
            test_name=test.name,
            passed=False,
            duration_ms=0,
            failures=[f"flow not found: {exc}"],
        )

    # Resolve input body
    input_spec = test.input
    if "bodyFile" in input_spec:
        body_path = project.root / input_spec["bodyFile"]
        if not body_path.exists():
            return TestResult(
                flow_id=test.flow,
                test_name=test.name,
                passed=False,
                duration_ms=0,
                failures=[f"input bodyFile not found: {input_spec['bodyFile']}"],
            )
        body = body_path.read_bytes()
    elif "bodyInline" in input_spec:
        body = input_spec["bodyInline"].encode("utf-8")
    else:
        body = b""

    headers = {k: str(v) for k, v in (input_spec.get("headers") or {}).items()}
    mocks = {m["target"]: m for m in test.mocks}

    ctx = execute_flow(
        flow=flow,
        input_body=body,
        input_headers=headers,
        resources=project.resources,
        mocks=mocks,
        engine=engine,
    )

    duration_ms = int((time.monotonic() - start) * 1000)

    failures: list[str] = []
    for assertion in test.assertions:
        ok, msg = _check_assertion(assertion, ctx, project)
        if not ok:
            failures.append(msg)

    mpl_records: list[dict[str, Any]] | None = None
    real_engine_blocked = False
    if engine == "real":
        mpl_records = mpl_records_from_context(ctx, flow.id)
        if isinstance(ctx.exception, ExecutionError) and (REAL_UNSUPPORTED_MARKER in str(ctx.exception)):
            real_engine_blocked = True
            failures.insert(0, str(ctx.exception))

    return TestResult(
        flow_id=test.flow,
        test_name=test.name,
        passed=not failures,
        duration_ms=duration_ms,
        failures=failures,
        mpl_records=mpl_records,
        real_engine_blocked=real_engine_blocked,
    )


def _check_assertion(assertion: dict[str, Any], ctx, project: Project) -> tuple[bool, str]:
    atype = assertion.get("type")
    if atype == "node.executed":
        node_id = assertion["node"]
        executed = any(t.node_id == node_id for t in ctx.trace)
        return (
            (executed, f"node '{node_id}' was not executed")
            if executed
            else (False, f"node '{node_id}' was not executed")
        )
    if atype == "node.not-executed":
        node_id = assertion["node"]
        executed = any(t.node_id == node_id for t in ctx.trace)
        return (
            (not executed, f"node '{node_id}' was unexpectedly executed")
            if not executed
            else (False, f"node '{node_id}' was unexpectedly executed")
        )
    if atype == "exchange.status":
        expected = assertion["equals"]
        actual = ctx.exchange_status
        if actual == expected:
            return True, ""
        return False, f"exchange.status: expected {expected}, got {actual}"
    if atype == "outbound.request":
        target = assertion["target"]
        call = next((c for c in ctx.outbound_calls if c["target"] == target), None)
        if call is None:
            return False, f"no outbound call recorded for target '{target}'"
        if "bodyMatchesXml" in assertion:
            expected_path = project.root / assertion["bodyMatchesXml"]
            if not expected_path.exists():
                return False, f"expected fixture not found: {assertion['bodyMatchesXml']}"
            expected = expected_path.read_bytes().decode("utf-8", errors="replace").strip()
            actual = call["body"].decode("utf-8", errors="replace").strip()
            if _xml_equal(expected, actual):
                return True, ""
            return (
                False,
                f"outbound body XML mismatch for '{target}'\n  expected: {expected[:200]}\n  actual:   {actual[:200]}",
            )
        if "bodyMatchesJson" in assertion:
            expected_path = project.root / assertion["bodyMatchesJson"]
            if not expected_path.exists():
                return False, f"expected fixture not found: {assertion['bodyMatchesJson']}"
            import json

            expected = json.loads(expected_path.read_text())
            try:
                actual = json.loads(call["body"].decode("utf-8"))
            except Exception:
                return False, f"outbound body is not valid JSON for '{target}'"
            if expected == actual:
                return True, ""
            return False, f"outbound body JSON mismatch for '{target}'"
        if "contains" in assertion:
            actual = call["body"].decode("utf-8", errors="replace")
            if assertion["contains"] in actual:
                return True, ""
            return False, f"outbound body for '{target}' does not contain: {assertion['contains']}"
        return True, ""
    if atype == "outbound.header.equals":
        target = assertion.get("target", "")
        name = assertion.get("name", "")
        expected = assertion.get("equals")
        call = next((c for c in ctx.outbound_calls if c["target"] == target), None)
        if call is None:
            return False, f"no outbound call recorded for target '{target}'"
        headers = call.get("headers", {})
        actual = headers.get(name)
        if actual is None:
            for k, v in headers.items():
                if k.lower() == name.lower():
                    actual = v
                    break
        if actual is not None and str(actual) == str(expected):
            return True, ""
        return False, f"outbound call '{target}' header '{name}': expected {expected!r}, got {actual!r}"
    if atype == "header.equals":
        name = assertion["name"]
        expected = assertion["equals"]
        actual = ctx.headers.get(name)
        if str(actual) == str(expected):
            return True, ""
        return False, f"header '{name}': expected {expected!r}, got {actual!r}"
    if atype == "property.equals":
        name = assertion["name"]
        expected = assertion["equals"]
        actual = ctx.properties.get(name)
        if str(actual) == str(expected):
            return True, ""
        return False, f"property '{name}': expected {expected!r}, got {actual!r}"
    if atype == "property.contains":
        name = assertion.get("name", "")
        needle = assertion.get("contains", "")
        actual = ctx.properties.get(name)
        if actual is None:
            return False, f"property '{name}' not found in exchange properties"
        if needle in str(actual):
            return True, ""
        return False, f"property '{name}' does not contain: {needle!r} (actual: {str(actual)!r})"
    if atype == "body.contains":
        needle = assertion["contains"]
        actual = ctx.body.decode("utf-8", errors="replace")
        if needle in actual:
            return True, ""
        return False, f"body does not contain: {needle}"
    return False, f"unknown assertion type: {atype}"


def _xml_equal(a: str, b: str) -> bool:
    """Compare two XML strings semantically (ignoring whitespace/attribute order)."""
    try:
        from lxml import etree

        ta = etree.fromstring(a.encode("utf-8"))
        tb = etree.fromstring(b.encode("utf-8"))
        return etree.tostring(ta, pretty_print=False) == etree.tostring(tb, pretty_print=False)
    except Exception:
        return a == b
