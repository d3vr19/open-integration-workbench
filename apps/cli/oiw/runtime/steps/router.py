"""Content-based router step.

Spec ref: §9.4 (`router.content-based`, fidelity=compatible-subset).
"""

from __future__ import annotations

import re
from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register


class ContentBasedRouter(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "router.content-based",
            "name": "Content-Based Router",
            "description": "Routes the message to one of several targets based on simple property/header expressions.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "conditions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "expression": {"type": "string"},
                            "target": {"type": "string"},
                        },
                        "required": ["id", "expression", "target"],
                    },
                },
            },
            "required": ["conditions"],
        }

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(node.id, "enter", "evaluating router conditions")
        for cond in node.config.get("conditions", []) or []:
            if _eval_condition(cond["expression"], ctx):
                ctx.properties["__router_selected_target__"] = cond["target"]
                ctx.properties["__router_selected_condition__"] = cond["id"]
                ctx.add_trace(
                    node.id, "exit", f"router selected condition '{cond['id']}' -> '{cond['target']}'"
                )
                return ctx
        # No condition matched
        ctx.properties["__router_selected_target__"] = None
        ctx.add_trace(node.id, "exit", "router: no condition matched")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "compatible-subset", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "TRUSTED"


def _eval_condition(expression: str, ctx: MessageContext) -> bool:
    """Evaluate a simple expression of the form:
    ${property.X} == 'value'  OR  ${header.Y} == 'value'  OR  true
    """
    expr = expression.strip()
    if expr == "true":
        return True
    if expr == "false":
        return False

    # Substitute placeholders
    def repl(match: re.Match) -> str:
        kind = match.group(1)  # 'property' or 'header'
        name = match.group(2)  # the name after the dot
        if kind == "property":
            return str(ctx.properties.get(name, ""))
        if kind == "header":
            return str(ctx.headers.get(name, ""))
        return ""

    substituted = re.sub(r"\$\{(property|header)\.([^}]+)\}", repl, expr)

    # Parse "X == 'Y'" or "X != 'Y'"
    m = re.match(r"^(.*?)\s*(==|!=)\s*'(.*)'$", substituted)
    if m:
        left, op, right = m.groups()
        if op == "==":
            return left == right
        return left != right

    # Fallback: truthy
    return bool(substituted)


register(ContentBasedRouter())
