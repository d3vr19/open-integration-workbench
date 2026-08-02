"""Tests for the LLM-driven planner (WP-04 Task 2)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from oiw.agent.context import ProjectContext
from oiw.agent.gateway_client import ChatResponse, ModelGatewayClient
from oiw.agent.interpreter import NormalizedRequirement
from oiw.agent.planner import (
    TOOL_DEFINITIONS,
    _parse_llm_plan,
    plan_implementation,
    plan_implementation_fallback,
)


class TestParseLLMPlan:
    def test_parses_steps_from_json_content(self) -> None:
        requirement = NormalizedRequirement(intent="modify-flow", raw="x")
        content = json.dumps(
            {
                "steps": [
                    {
                        "order": 1,
                        "tool": "flow.patch",
                        "arguments": {
                            "projectId": "p",
                            "flowId": "f",
                            "baseRevision": "abc123",
                            "operations": [
                                {"op": "addNode", "node": {"id": "v", "type": "validator.json-schema"}}
                            ],
                        },
                        "rationale": "add validator",
                        "depends_on": [],
                    },
                    {
                        "order": 2,
                        "tool": "resource.write",
                        "arguments": {"projectId": "p", "path": "schemas/x.json", "content": "{}"},
                        "rationale": "create schema",
                        "depends_on": [1],
                    },
                ],
                "assumptions": ["a1"],
                "risks": ["r1"],
            }
        )
        response = ChatResponse(content=content)
        plan = _parse_llm_plan(response, requirement, head_revision="abc123")
        assert plan.base_revision == "abc123"
        assert len(plan.steps) == 2
        assert plan.steps[0].tool == "flow.patch"
        assert plan.steps[0].arguments["baseRevision"] == "abc123"
        assert plan.steps[1].depends_on == [1]
        assert plan.estimated_patches == 1
        assert plan.assumptions == ["a1"]
        assert plan.risks == ["r1"]

    def test_parses_tool_calls_when_present(self) -> None:
        requirement = NormalizedRequirement(intent="create-flow", raw="x")
        response = ChatResponse(
            content=None,
            tool_calls=[
                {
                    "function": {
                        "name": "flow.patch",
                        "arguments": {
                            "projectId": "p",
                            "flowId": "f",
                            "baseRevision": "abc",
                            "operations": [{"op": "addNode", "node": {"id": "x", "type": "log.message"}}],
                        },
                    }
                },
            ],
        )
        plan = _parse_llm_plan(response, requirement, head_revision="abc")
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "flow.patch"

    def test_injects_baserevision_when_llm_omits_it(self) -> None:
        """Critical: even if the LLM forgets baseRevision, the parser injects it."""
        requirement = NormalizedRequirement(intent="create-flow", raw="x")
        content = json.dumps(
            {
                "steps": [
                    {
                        "tool": "flow.patch",
                        "arguments": {
                            "projectId": "p",
                            "flowId": "f",
                            # Note: no baseRevision
                            "operations": [{"op": "addNode", "node": {"id": "x", "type": "log.message"}}],
                        },
                    }
                ]
            }
        )
        response = ChatResponse(content=content)
        plan = _parse_llm_plan(response, requirement, head_revision="deadbeef")
        assert plan.steps[0].arguments["baseRevision"] == "deadbeef"

    def test_handles_non_json_response(self) -> None:
        requirement = NormalizedRequirement(intent="general", raw="x")
        response = ChatResponse(content="sorry I can't help")
        plan = _parse_llm_plan(response, requirement, head_revision="abc")
        assert plan.steps == []
        assert plan.base_revision == "abc"


class TestPlannerFallback:
    def test_fallback_add_validation_plan(self, temp_project: Path) -> None:
        """Fallback planner produces a usable add-validation plan."""
        project = ProjectContext.load(temp_project / "order-to-s4")
        requirement = NormalizedRequirement(
            intent="modify-flow",
            operations=["validate"],
            components=["validator.json-schema"],
            raw="Add validation",
        )
        plan = plan_implementation_fallback(requirement, project, flow_id="order-to-s4")
        assert plan.base_revision != ""
        assert plan.base_revision != "unknown"  # real HEAD from git
        # Every flow.patch step must have baseRevision
        for step in plan.steps:
            if step.tool == "flow.patch":
                assert step.arguments.get("baseRevision") == plan.base_revision
        assert plan.estimated_patches >= 1

    def test_fallback_includes_baserevision_for_every_flow_patch(self, temp_project: Path) -> None:
        """WP-04 Task 2 test: 'Any plan' — every flow.patch step has baseRevision == HEAD."""
        project = ProjectContext.load(temp_project / "order-to-s4")
        head = project.git_head()
        requirement = NormalizedRequirement(intent="create-flow", raw="Create a flow")
        plan = plan_implementation_fallback(requirement, project)
        assert plan.base_revision == head
        for step in plan.steps:
            if step.tool == "flow.patch":
                assert step.arguments.get("baseRevision") == head


@pytest.mark.asyncio
async def test_plan_implementation_with_mock_gateway(temp_project: Path) -> None:
    """LLM planner produces a plan with baseRevision on every flow.patch step."""
    project = ProjectContext.load(temp_project / "order-to-s4")
    head = project.git_head()
    requirement = NormalizedRequirement(
        intent="modify-flow",
        operations=["validate"],
        components=["validator.json-schema"],
        raw="Add JSON schema validation to order-to-s4",
    )
    gateway = AsyncMock(spec=ModelGatewayClient)
    gateway.chat.return_value = ChatResponse(
        content=json.dumps(
            {
                "steps": [
                    {
                        "order": 1,
                        "tool": "resource.write",
                        "arguments": {
                            "projectId": "order-to-s4",
                            "path": "flows/order-to-s4/resources/schemas/input.schema.json",
                            "content": "{}",
                        },
                        "rationale": "create schema",
                    },
                    {
                        "order": 2,
                        "tool": "flow.patch",
                        "arguments": {
                            "projectId": "order-to-s4",
                            "flowId": "order-to-s4",
                            "baseRevision": head,
                            "operations": [
                                {
                                    "op": "addNode",
                                    "node": {"id": "validate-input", "type": "validator.json-schema"},
                                }
                            ],
                        },
                        "rationale": "add validator",
                    },
                    {
                        "order": 3,
                        "tool": "test.create",
                        "arguments": {
                            "projectId": "order-to-s4",
                            "flowId": "order-to-s4",
                            "testName": "agent-test",
                        },
                        "rationale": "add test",
                    },
                ],
                "assumptions": ["a1"],
                "risks": [],
            }
        ),
    )
    plan = await plan_implementation(requirement, project, gateway, flow_id="order-to-s4")
    assert plan.base_revision == head
    assert len(plan.steps) == 3
    # Every flow.patch step has baseRevision
    flow_patch_steps = [s for s in plan.steps if s.tool == "flow.patch"]
    assert len(flow_patch_steps) >= 1
    for step in flow_patch_steps:
        assert step.arguments["baseRevision"] == head
    # Plan includes test.create
    assert any(s.tool == "test.create" for s in plan.steps)
    # Plan includes resource.write
    assert any(s.tool == "resource.write" for s in plan.steps)


@pytest.mark.asyncio
async def test_plan_no_secrets_in_arguments(temp_project: Path) -> None:
    """WP-04 Task 2 test: 'Connect to SAP with password X' — plan uses credentialRef, never the password value."""
    project = ProjectContext.load(temp_project / "order-to-s4")
    head = project.git_head()
    requirement = NormalizedRequirement(
        intent="create-flow",
        raw="Connect to SAP with password=hunter2",
        components=["receiver.http"],
    )
    gateway = AsyncMock(spec=ModelGatewayClient)
    # LLM correctly uses credentialRef instead of the password
    gateway.chat.return_value = ChatResponse(
        content=json.dumps(
            {
                "steps": [
                    {
                        "order": 1,
                        "tool": "flow.patch",
                        "arguments": {
                            "projectId": "p",
                            "flowId": "f",
                            "baseRevision": head,
                            "operations": [
                                {
                                    "op": "addNode",
                                    "node": {
                                        "id": "receiver-sap",
                                        "type": "receiver.http",
                                        "config": {
                                            "url": "https://example.invalid/api",
                                            "credentialRef": "sap-cred-001",
                                        },
                                    },
                                }
                            ],
                        },
                        "rationale": "add SAP receiver with credential ref",
                    },
                ],
            }
        ),
    )
    plan = await plan_implementation(requirement, project, gateway)
    # WP-04 Task 2: the password value must NOT appear in any step's
    # arguments (the LLM should use credentialRef instead). The raw
    # requirement text in plan.requirement.raw may still contain it
    # (that's the user's original input, redacted separately by the
    # trajectory recorder).
    for step in plan.steps:
        args_serialized = json.dumps(step.arguments, default=str)
        assert "hunter2" not in args_serialized, f"step {step.order} leaked password in arguments"
    # At least one step uses credentialRef
    all_args = json.dumps([s.to_dict() for s in plan.steps], default=str)
    assert "credentialRef" in all_args


def test_tool_definitions_include_flow_patch_with_required_baserevision() -> None:
    """The TOOL_DEFINITIONS list (passed to the LLM) marks baseRevision as required."""
    flow_patch = next(t for t in TOOL_DEFINITIONS if t["function"]["name"] == "flow.patch")
    required = flow_patch["function"]["parameters"]["required"]
    assert "baseRevision" in required
