"""LLM-driven plan generator (WP-04 Task 2).

Replaces the hardcoded if/elif planner in
`apps/server-python-prototype/oiw_server/agent.py::plan_implementation`
with an LLM call that produces a structured `ImplementationPlan` of
`PlanStep`s. Each `flow.patch` step MUST include `baseRevision` matching
the HEAD captured at planning time — the executor (Task 3) validates
this before dispatching.

Fallback path: if the gateway is unreachable, the planner falls back to
the existing hardcoded planner (delegated to
`apps.server_python_prototype.oiw_server.agent.plan_implementation` if
importable, else an inline equivalent).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .context import ProjectContext
from .gateway_client import ChatResponse, ModelGatewayClient
from .interpreter import NormalizedRequirement

OIW_W014_PLANNER = "OIW-W014: LLM planner unavailable; using hardcoded fallback planner."


@dataclass
class PlanStep:
    """A single step in an implementation plan.

    Field names are aligned with the MCP tool-call schema. `arguments`
    MUST match the MCP tool's inputSchema; the executor validates this
    before dispatching.
    """

    order: int
    tool: str  # MCP tool name: flow.patch, resource.write, test.create, ...
    arguments: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    depends_on: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ImplementationPlan:
    """A complete implementation plan.

    `base_revision` is the HEAD captured at planning time. Every
    `flow.patch` step's `arguments["baseRevision"]` MUST equal this.
    The executor enforces this (Task 3 + Task 6).
    """

    requirement: NormalizedRequirement
    steps: list[PlanStep] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    estimated_patches: int = 0
    base_revision: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement.to_dict(),
            "steps": [s.to_dict() for s in self.steps],
            "assumptions": self.assumptions,
            "risks": self.risks,
            "estimatedPatches": self.estimated_patches,
            "baseRevision": self.base_revision,
        }


def _load_system_prompt() -> str:
    p = Path(__file__).parent / "prompts" / "planner.md"
    return p.read_text(encoding="utf-8")


def _build_planning_prompt(
    requirement: NormalizedRequirement,
    project_context: ProjectContext,
    head_revision: str,
    flow_id: str | None = None,
) -> str:
    """Build the user-side prompt for the planner LLM call."""
    parts = [
        "## Normalized requirement",
        json.dumps(requirement.to_dict(), indent=2, default=str),
        "",
        "## Project context",
        project_context.to_prompt_context(flow_id),
        "",
        f"## Current HEAD (baseRevision for every flow.patch step)\n{head_revision}",
        "",
        "## Task",
        "Produce a JSON object per the system prompt schema. Every flow.patch "
        "step MUST include `arguments.baseRevision` = the HEAD sha above. "
        "Do not invent tool names. Do not include secret values.",
    ]
    return "\n".join(parts)


# Minimal tool definitions for the LLM's function-calling. The MCP server
# is the source of truth for full schemas; this is the subset the planner
# needs to choose steps. (We do not pass the full MCP schemas because they
# are large and the LLM tends to overfit to field names.)
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "flow.create",
            "description": "Create a new integration flow. Use this BEFORE flow.patch when creating a brand-new flow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "flowId": {"type": "string"},
                    "name": {"type": "string"},
                    "initialNodes": {"type": "array", "items": {"type": "object"}},
                    "initialEdges": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["projectId", "flowId", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flow.patch",
            "description": "Apply typed patch operations to an integration flow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "flowId": {"type": "string"},
                    "baseRevision": {"type": "string"},
                    "operations": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["projectId", "flowId", "baseRevision", "operations"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resource.write",
            "description": "Write a resource file (schema, script, mapping, fixture).",
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "resourceType": {"type": "string"},
                },
                "required": ["projectId", "path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "test.create",
            "description": "Create a FlowTest YAML.",
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "flowId": {"type": "string"},
                    "testName": {"type": "string"},
                    "bodyInline": {"type": "string"},
                    "assertions": {"type": "array"},
                    "mocks": {"type": "array"},
                },
                "required": ["projectId", "flowId", "testName"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flow.validate",
            "description": "Run validators on the project (read-only).",
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "strict": {"type": "boolean"},
                },
                "required": ["projectId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "test.run",
            "description": "Run all tests for a flow (read-only).",
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"},
                    "flowId": {"type": "string"},
                },
                "required": ["projectId"],
            },
        },
    },
]


def _parse_llm_plan(
    response: ChatResponse, requirement: NormalizedRequirement, head_revision: str
) -> ImplementationPlan:
    """Parse the LLM's response (either tool_calls or JSON content) into a plan."""
    steps: list[PlanStep] = []
    assumptions: list[str] = []
    risks: list[str] = []

    # Prefer structured tool_calls if the model produced them
    if response.tool_calls:
        for i, tc in enumerate(response.tool_calls, start=1):
            fn = tc.get("function", {})
            steps.append(
                PlanStep(
                    order=i,
                    tool=fn.get("name", "unknown"),
                    arguments=fn.get("arguments", {})
                    if isinstance(fn.get("arguments"), dict)
                    else _safe_json(fn.get("arguments")),
                    rationale=fn.get("description", ""),
                    depends_on=[],
                )
            )
    elif response.content:
        # Fall back to parsing JSON content
        text = response.content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            data = json.loads(match.group(0)) if match else {"steps": [], "risks": ["LLM returned non-JSON"]}
        for i, s in enumerate(data.get("steps", []), start=1):
            steps.append(
                PlanStep(
                    order=s.get("order", i),
                    tool=s.get("tool", "unknown"),
                    arguments=s.get("arguments", {}) or {},
                    rationale=s.get("rationale", ""),
                    depends_on=s.get("depends_on", []) or [],
                )
            )
        assumptions = data.get("assumptions", []) or []
        risks = data.get("risks", []) or []

    # Enforce baseRevision on every flow.patch step (defensive — the prompt
    # asks for it, but the LLM may forget)
    for step in steps:
        if step.tool == "flow.patch" and not step.arguments.get("baseRevision"):
            step.arguments["baseRevision"] = head_revision

    return ImplementationPlan(
        requirement=requirement,
        steps=steps,
        assumptions=assumptions,
        risks=risks,
        estimated_patches=sum(1 for s in steps if s.tool == "flow.patch"),
        base_revision=head_revision,
    )


def _safe_json(s: Any) -> dict[str, Any]:
    if isinstance(s, dict):
        return s
    if isinstance(s, str):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return {}
    return {}


async def plan_implementation(
    requirement: NormalizedRequirement,
    project_context: ProjectContext,
    gateway: ModelGatewayClient,
    flow_id: str | None = None,
) -> ImplementationPlan:
    """Generate an implementation plan via the LLM.

    Raises:
        RuntimeError: if the gateway call fails (caller should fall back).
    """
    head_revision = project_context.git_head()
    messages = [
        {"role": "system", "content": _load_system_prompt()},
        {
            "role": "user",
            "content": _build_planning_prompt(requirement, project_context, head_revision, flow_id),
        },
    ]
    response = await gateway.chat(
        messages=messages,
        tools=TOOL_DEFINITIONS,
        max_tokens=4096,
        temperature=0.2,
    )
    return _parse_llm_plan(response, requirement, head_revision)


# ---------------------------------------------------------------------------
# Hardcoded fallback (spec §14: LLM-unavailable path)
# ---------------------------------------------------------------------------


def plan_implementation_fallback(
    requirement: NormalizedRequirement,
    project_context: ProjectContext,
    flow_id: str | None = None,
) -> ImplementationPlan:
    """Hardcoded planner used when the LLM is unavailable.

    Delegates to the existing keyword-based planner in
    `apps.server_python_prototype.oiw_server.agent.plan_implementation`
    if importable, otherwise uses an inline equivalent.
    """
    head_revision = project_context.git_head()

    # Try to delegate to the existing server-side planner (it has the
    # most up-to-date plan templates for create-flow / add-validation / etc.)
    try:
        from oiw_server.agent import (
            NormalizedRequirement as _LegacyReq,
        )
        from oiw_server.agent import (  # type: ignore[import-not-found]
            plan_implementation as _legacy_plan,
        )

        # Convert our NormalizedRequirement to the legacy shape (which
        # uses fewer fields)
        legacy_req = _LegacyReq(
            intent=_map_intent_to_legacy(requirement),
            source_protocol=requirement.source_protocol,
            target_protocol=requirement.target_protocol,
            operations=requirement.operations,
            archetype=requirement.archetype,
            raw=requirement.raw,
        )
        legacy_plan = _legacy_plan(
            legacy_req, project_context.project_id, flow_id, base_revision=head_revision
        )
        # Convert legacy PlanSteps to our PlanStep shape
        steps = [
            PlanStep(
                order=s.index,
                tool=s.tool,
                arguments=s.arguments,
                rationale=s.description,
                depends_on=[],
            )
            for s in legacy_plan.steps
        ]
        return ImplementationPlan(
            requirement=requirement,
            steps=steps,
            assumptions=legacy_plan.assumptions,
            risks=legacy_plan.risks,
            estimated_patches=sum(1 for s in steps if s.tool == "flow.patch"),
            base_revision=head_revision,
        )
    except Exception:
        pass

    # Inline fallback: minimal "add validation" plan
    steps: list[PlanStep] = []
    if requirement.intent == "modify-flow" and "validate" in requirement.operations:
        steps.append(
            PlanStep(
                order=1,
                tool="flow.patch",
                arguments={
                    "projectId": project_context.project_id,
                    "flowId": flow_id or "order-to-s4",
                    "baseRevision": head_revision,
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "validate-input",
                                "type": "validator.json-schema",
                                "config": {"schema": "resources/schemas/input.schema.json"},
                                "fidelity": "compatible-subset",
                            },
                        }
                    ],
                },
                rationale="Add JSON Schema validator after sender (hardcoded fallback).",
            )
        )
    return ImplementationPlan(
        requirement=requirement,
        steps=steps,
        assumptions=["LLM unavailable — using minimal hardcoded plan."],
        risks=["Fallback plan may not match user intent precisely."],
        estimated_patches=sum(1 for s in steps if s.tool == "flow.patch"),
        base_revision=head_revision,
    )


def _map_intent_to_legacy(requirement: NormalizedRequirement) -> str:
    """Map our intent taxonomy to the legacy planner's taxonomy.

    The legacy planner recognizes: create-flow, add-validation, add-test,
    modify-flow, general.
    """
    intent = requirement.intent
    operations = requirement.operations or []
    components = requirement.components or []
    if intent == "fix-flow":
        return "modify-flow"
    if intent == "refactor":
        return "modify-flow"
    # If the requirement is about adding validation, map to add-validation
    # (the legacy planner only generates steps for that specific intent)
    if "validate" in operations or any("validator" in c for c in components):
        return "add-validation"
    if intent == "add-test":
        return "add-test"
    return intent


__all__ = [
    "PlanStep",
    "ImplementationPlan",
    "plan_implementation",
    "plan_implementation_fallback",
    "TOOL_DEFINITIONS",
    "OIW_W014_PLANNER",
]
