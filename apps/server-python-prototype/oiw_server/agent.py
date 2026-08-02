"""Agent pipeline — requirement-to-plan-to-implementation.

Spec ref: §12.2 (Agent Pipeline), §12.3 (Interaction Modes).

Pipeline:
  1. Requirements Interpreter — normalizes NL requirement into intent + protocol + operations
  2. Integration Planner — produces step-by-step plan from normalized requirement
  3. Implementation Agent — executes typed tool calls (flow.patch, resource.write, test.create)
  4. Validation & Test Agent — runs validation, tests, simulation

Each stage produces a structured result. The full pipeline can be invoked
via the API endpoints POST /agents:plan and POST /agents:implement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormalizedRequirement:
    """Output of the Requirements Interpreter (spec §12.2)."""

    intent: str  # "create-flow" | "modify-flow" | "add-validation" | "add-test" | "general"
    source_protocol: str | None = None  # "https" | "sftp" | "soap" | "odata" | "jms"
    target_protocol: str | None = None
    operations: list[str] = field(default_factory=list)  # "validate", "transform", "route", etc.
    archetype: str | None = None  # "api-to-erp", "file-to-api", etc.
    raw: str = ""

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "sourceProtocol": self.source_protocol,
            "targetProtocol": self.target_protocol,
            "operations": self.operations,
            "archetype": self.archetype,
            "raw": self.raw,
        }


@dataclass
class PlanStep:
    """A single step in an implementation plan."""

    index: int
    tool: str  # MCP tool name: "flow.patch", "resource.write", "test.run", etc.
    description: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "tool": self.tool,
            "description": self.description,
            "arguments": self.arguments,
        }


@dataclass
class ImplementationPlan:
    """Output of the Integration Planner (spec §12.2)."""

    requirement: NormalizedRequirement
    steps: list[PlanStep] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "requirement": self.requirement.to_dict(),
            "steps": [s.to_dict() for s in self.steps],
            "assumptions": self.assumptions,
            "risks": self.risks,
        }


@dataclass
class ExecutionResult:
    """Output of the Implementation Agent (spec §12.2)."""

    plan: ImplementationPlan
    step_results: list[dict[str, Any]] = field(default_factory=list)
    success: bool = True
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "plan": self.plan.to_dict(),
            "stepResults": self.step_results,
            "success": self.success,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------
# Stage 1: Requirements Interpreter
# ---------------------------------------------------------------------


def interpret_requirement(raw_requirement: str) -> NormalizedRequirement:
    """Normalize a natural-language requirement.

    Spec §12.2: "Requirements Interpreter ← normalizes intent, identifies archetype"

    This is a rule-based interpreter (no LLM call yet — the LLM-assisted
    version will use the model gateway once Phase 3 is further along).
    It extracts intent, protocols, operations, and archetype from keywords.
    """
    text = raw_requirement.lower()

    # Intent detection — check specific intents before generic "create"
    intent = "general"
    if "validation" in text or ("validate" in text and "add" in text):
        intent = "add-validation"
    elif "test" in text and ("add" in text or "create" in text):
        intent = "add-test"
    elif any(w in text for w in ["modify", "change", "update"]):
        intent = "modify-flow"
    elif any(w in text for w in ["create", "new", "build a flow"]):
        intent = "create-flow"

    # Protocol detection
    protocols = {
        "https": ["http", "https", "rest", "api"],
        "sftp": ["sftp", "file", "csv"],
        "soap": ["soap", "xml"],
        "odata": ["odata"],
        "jms": ["jms", "queue", "message"],
    }
    detected: set[str] = set()
    for proto, keywords in protocols.items():
        if any(kw in text for kw in keywords):
            detected.add(proto)

    source_protocol = None
    target_protocol = None
    if detected:
        # Heuristic: "from X" → source, "to Y" → target
        from_match = re.search(r"from\s+(\w+)", text)
        to_match = re.search(r"to\s+(\w+)", text)
        if from_match:
            for p in detected:
                if p in from_match.group(1):
                    source_protocol = p
        if to_match:
            for p in detected:
                if p in to_match.group(1):
                    target_protocol = p
        # Fallback: first detected = source, last = target
        if not source_protocol and detected:
            source_protocol = sorted(detected)[0]
        if not target_protocol and len(detected) > 1:
            target_protocol = sorted(detected)[-1]

    # Operations detection
    operations: list[str] = []
    op_keywords = {
        "validate": ["validate", "validation", "schema"],
        "transform": ["transform", "mapping", "xslt", "convert"],
        "route": ["route", "router", "routing", "branch", "condition"],
        "filter": ["filter"],
        "split": ["split", "splitter"],
        "gather": ["gather", "aggregate"],
        "encode": ["encode", "base64"],
        "log": ["log"],
    }
    for op, keywords in op_keywords.items():
        if any(kw in text for kw in keywords):
            operations.append(op)

    # Archetype detection
    archetype = None
    if source_protocol and target_protocol:
        archetype = f"{source_protocol}-to-{target_protocol}"
    elif "api-to-erp" in text or "erp" in text:
        archetype = "api-to-erp"
    elif "file-to-api" in text:
        archetype = "file-to-api"

    return NormalizedRequirement(
        intent=intent,
        source_protocol=source_protocol,
        target_protocol=target_protocol,
        operations=operations,
        archetype=archetype,
        raw=raw_requirement,
    )


# ---------------------------------------------------------------------
# Stage 2: Integration Planner
# ---------------------------------------------------------------------


def plan_implementation(
    requirement: NormalizedRequirement,
    project_id: str,
    flow_id: str | None = None,
    base_revision: str | None = None,
) -> ImplementationPlan:
    """Produce a step-by-step implementation plan.

    Spec §12.2: "Integration Planner ← produces step-by-step implementation plan"
    WP-04 Task 2 (fallback): every flow.patch step MUST include baseRevision
    matching HEAD. If `base_revision` is None the caller (typically the
    REST route) is expected to supply HEAD; we leave it None here so the
    MCP handler's required-field check rejects the patch loudly rather
    than silently applying with a fake revision.
    """
    steps: list[PlanStep] = []
    assumptions: list[str] = []
    risks: list[str] = []
    idx = 1

    if requirement.intent == "create-flow":
        # Plan: create flow skeleton → add nodes → add edges → validate
        assumptions.append("A new flow ID will be generated from the requirement")
        assumptions.append("Default fidelity is 'simulated' for all new nodes")

        steps.append(
            PlanStep(
                index=idx,
                tool="flow.patch",
                description="Create flow skeleton with sender + receiver",
                arguments={
                    "projectId": project_id,
                    "flowId": flow_id or "new-flow",
                    "baseRevision": base_revision,
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "sender-http",
                                "type": "sender.http",
                                "config": {"path": "/new", "methods": ["POST"]},
                                "fidelity": "simulated",
                            },
                        },
                        {
                            "op": "addNode",
                            "node": {
                                "id": "receiver-http",
                                "type": "receiver.http",
                                "config": {
                                    "url": "https://example.invalid/api",
                                    "method": "POST",
                                    "timeoutSeconds": 30,
                                },
                                "fidelity": "simulated",
                            },
                        },
                        {"op": "addEdge", "from": "sender-http", "to": "receiver-http"},
                    ],
                },
            )
        )
        idx += 1

    elif requirement.intent == "add-validation":
        assumptions.append("A validator.json-schema node will be added after the sender")
        assumptions.append("A JSON Schema resource will be created")

        steps.append(
            PlanStep(
                index=idx,
                tool="flow.patch",
                description="Add JSON Schema validator node after sender",
                arguments={
                    "projectId": project_id,
                    "flowId": flow_id or "order-to-s4",
                    "baseRevision": base_revision,
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "validate-input",
                                "type": "validator.json-schema",
                                "config": {"schema": "resources/schemas/input.schema.json"},
                                "fidelity": "compatible-subset",
                            },
                        },
                    ],
                },
            )
        )
        idx += 1

        steps.append(
            PlanStep(
                index=idx,
                tool="resource.write",
                description="Create input JSON Schema resource",
                arguments={
                    "projectId": project_id,
                    "path": f"flows/{flow_id or 'order-to-s4'}/resources/schemas/input.schema.json",
                    "content": '{\n  "$schema": "http://json-schema.org/draft-07/schema#",\n  "type": "object",\n  "required": ["id"],\n  "properties": {\n    "id": {"type": "string"}\n  }\n}',
                },
            )
        )
        idx += 1

    elif requirement.intent == "add-test":
        assumptions.append("A new FlowTest will be created for the specified flow")

        steps.append(
            PlanStep(
                index=idx,
                tool="test.create",
                description="Create test definition YAML via test.create tool",
                arguments={
                    "projectId": project_id,
                    "flowId": flow_id or "order-to-s4",
                    "testName": "agent-generated",
                    "bodyInline": "{}",
                    "assertions": [{"type": "exchange.status", "equals": "COMPLETED"}],
                    "mocks": [],
                },
            )
        )
        idx += 1

    elif requirement.intent == "modify-flow":
        assumptions.append("Existing flow will be modified with requested operations")
        if not requirement.operations:
            risks.append("No specific operations detected — plan may be incomplete")

    # Always add validation + test steps at the end
    if steps:
        steps.append(
            PlanStep(
                index=idx,
                tool="flow.validate",
                description="Validate the project after changes",
                arguments={"projectId": project_id, "strict": True},
            )
        )
        idx += 1

        steps.append(
            PlanStep(
                index=idx,
                tool="test.run",
                description="Run all tests to verify the changes",
                arguments={"projectId": project_id, "flowId": flow_id},
            )
        )
        idx += 1

    if not steps:
        risks.append("No plan could be generated for this requirement — intent not recognized")

    return ImplementationPlan(
        requirement=requirement,
        steps=steps,
        assumptions=assumptions,
        risks=risks,
    )


# ---------------------------------------------------------------------
# Stage 3: Implementation Agent (executor)
# ---------------------------------------------------------------------


def execute_plan(plan: ImplementationPlan) -> ExecutionResult:
    """Execute a plan by calling the MCP tools.

    Spec §12.2: "Implementation Agent ← executes typed tool calls"
    Spec §12.1: "The LLM never edits files directly; all mutations go
    through typed patch operations."

    This executor calls the same dispatch functions the MCP server uses.
    """
    from oiw_mcp.tools import dispatch_tool

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    success = True

    for step in plan.steps:
        try:
            result_text = dispatch_tool(step.tool, step.arguments)
            # Try to parse as JSON; if it fails, keep as text
            import json

            try:
                result_data = json.loads(result_text)
            except json.JSONDecodeError:
                result_data = {"raw": result_text}

            results.append(
                {
                    "stepIndex": step.index,
                    "tool": step.tool,
                    "description": step.description,
                    "result": result_data,
                    "success": "error" not in result_data if isinstance(result_data, dict) else True,
                }
            )

            if isinstance(result_data, dict) and "error" in result_data:
                errors.append(f"Step {step.index} ({step.tool}): {result_data['error']}")
                success = False

        except Exception as exc:
            results.append(
                {
                    "stepIndex": step.index,
                    "tool": step.tool,
                    "description": step.description,
                    "error": str(exc),
                    "success": False,
                }
            )
            errors.append(f"Step {step.index} ({step.tool}): {type(exc).__name__}: {exc}")
            success = False

    return ExecutionResult(
        plan=plan,
        step_results=results,
        success=success,
        errors=errors,
    )
