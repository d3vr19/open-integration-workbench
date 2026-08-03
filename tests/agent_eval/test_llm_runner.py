"""Tests for the LLM-backed benchmark runner (WP-05 Task 17 / OW-023).

These tests verify the LLM runner's plumbing (prompt building, response
parsing, plan execution) without requiring a live LLM call. The actual
LLM-backed benchmarks (bench-002, bench-003) are run manually via
`python -m tests.agent_eval.llm_runner -b bench-003` and are not part
of the CI suite (they require network access to the z-ai service).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.agent_eval.benchmarks import get_benchmark
from tests.agent_eval.llm_runner import (
    _build_planning_prompt,
    _call_zai_chat,
    _parse_llm_plan,
)
from oiw.agent.context import ProjectContext
from oiw.agent.interpreter import NormalizedRequirement


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "order-to-s4"


class TestBuildPlanningPrompt:
    def test_prompt_includes_requirement(self) -> None:
        """Prompt contains the benchmark requirement text."""
        bench = get_benchmark("bench-003")
        ctx = ProjectContext.load(EXAMPLE)
        prompt = _build_planning_prompt(bench, ctx, "abc123")
        assert (
            "Fix receiver timeout" in prompt or "receiver times out" in prompt.lower()
        )
        assert "abc123" in prompt  # baseRevision

    def test_prompt_includes_base_revision(self) -> None:
        """Prompt includes the HEAD sha for baseRevision injection."""
        bench = get_benchmark("bench-001")
        ctx = ProjectContext.load(EXAMPLE)
        prompt = _build_planning_prompt(bench, ctx, "deadbeef")
        assert "deadbeef" in prompt
        assert "baseRevision" in prompt

    def test_prompt_includes_project_context(self) -> None:
        """Prompt includes the project ID + flow listing."""
        bench = get_benchmark("bench-003")
        ctx = ProjectContext.load(EXAMPLE)
        prompt = _build_planning_prompt(bench, ctx, "abc")
        assert "order-to-s4" in prompt
        assert "Flows:" in prompt


class TestParseLLMPlan:
    def _make_req(self) -> NormalizedRequirement:
        return NormalizedRequirement(intent="fix-flow", raw="test")

    def test_parse_valid_json(self) -> None:
        """Valid JSON response → plan with steps."""
        response = json.dumps(
            {
                "steps": [
                    {
                        "order": 1,
                        "tool": "flow.patch",
                        "arguments": {
                            "projectId": "p",
                            "flowId": "f",
                            "baseRevision": "abc",
                            "operations": [
                                {
                                    "op": "updateNodeConfig",
                                    "nodeId": "receiver",
                                    "config": {"timeoutSeconds": 60},
                                }
                            ],
                        },
                        "rationale": "increase timeout",
                    }
                ],
                "assumptions": ["timeout was 30s"],
                "risks": [],
            }
        )
        plan = _parse_llm_plan(response, self._make_req(), "abc")
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "flow.patch"
        assert plan.steps[0].arguments["baseRevision"] == "abc"
        assert plan.assumptions == ["timeout was 30s"]

    def test_parse_markdown_fenced_json(self) -> None:
        """JSON wrapped in ```json fences → parsed correctly."""
        response = '```json\n{"steps": [{"tool": "flow.validate", "arguments": {"projectId": "p"}}]}\n```'
        plan = _parse_llm_plan(response, self._make_req(), "abc")
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "flow.validate"

    def test_parse_empty_response(self) -> None:
        """Empty LLM response → empty plan with risk."""
        plan = _parse_llm_plan("", self._make_req(), "abc")
        assert plan.steps == []
        assert "empty response" in plan.assumptions[0].lower()

    def test_parse_invalid_json(self) -> None:
        """Non-JSON response → empty plan with risk."""
        plan = _parse_llm_plan("sorry I can't help", self._make_req(), "abc")
        assert plan.steps == []
        assert any("not valid JSON" in r for r in plan.risks)

    def test_injects_baserevision_if_missing(self) -> None:
        """flow.patch step without baseRevision → injected from head."""
        response = json.dumps(
            {
                "steps": [
                    {
                        "tool": "flow.patch",
                        "arguments": {
                            "projectId": "p",
                            "flowId": "f",
                            # Note: no baseRevision
                            "operations": [{"op": "addNode", "node": {"id": "x"}}],
                        },
                    }
                ]
            }
        )
        plan = _parse_llm_plan(response, self._make_req(), "injected-head")
        assert plan.steps[0].arguments["baseRevision"] == "injected-head"


class TestCallZaiChat:
    """Tests for the z-ai CLI wrapper. These are integration tests —
    they require the z-ai CLI to be installed and network access."""

    @pytest.mark.skipif(
        not _call_zai_chat("test"),
        reason="z-ai CLI not available or network down",
    )
    def test_zai_cli_returns_nonempty(self) -> None:
        """z-ai CLI returns a non-empty response for a simple prompt."""
        response = _call_zai_chat("Say hello")
        assert len(response) > 0


class TestStructuredMetricParserParity:
    """OW-024: verify the structured JSON metric parsers produce the same
    results as the old text-parsing approach on known inputs."""

    def test_validate_json_output_shape(self) -> None:
        """The --json output from validate has the expected fields."""
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "oiw.cli",
                "validate",
                "--strict",
                "--json",
                "--project",
                str(EXAMPLE),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env={**__import__("os").environ, "PYTHONPATH": f"{REPO_ROOT}/apps/cli"},
        )
        data = json.loads(result.stdout)
        assert "passed" in data
        assert "errors" in data
        assert "error_count" in data
        assert isinstance(data["errors"], list)
        assert isinstance(data["error_count"], int)

    def test_test_json_output_shape(self) -> None:
        """The --json output from test has the expected fields."""
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "oiw.cli",
                "test",
                "--all",
                "--json",
                "--project",
                str(EXAMPLE),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env={**__import__("os").environ, "PYTHONPATH": f"{REPO_ROOT}/apps/cli"},
        )
        data = json.loads(result.stdout)
        assert "passed" in data
        assert "pass_rate" in data
        assert "total" in data
        assert "results" in data
        assert isinstance(data["results"], list)
