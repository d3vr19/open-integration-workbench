"""Filter step.

Spec ref: §9.4 (`filter`, fidelity=compatible-subset, XPath/predicate expressions).
"""

from __future__ import annotations

from typing import Any

from ...project import FlowNode
from ..context import ExchangeStatus, MessageContext
from .base import StepPlugin, register


class Filter(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "filter",
            "name": "Filter",
            "description": "Drops the message if the filter expression evaluates to false.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Predicate expression, e.g. ${property.X} == 'Y'",
                },
            },
            "required": ["expression"],
        }

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(node.id, "enter", "evaluating filter")
        expr = node.config.get("expression", "true")
        from .router import _eval_condition

        try:
            keep = _eval_condition(expr, ctx)
        except Exception as exc:
            ctx.exchange_status = ExchangeStatus.FAILED
            ctx.exception = exc
            ctx.add_trace(node.id, "error", f"filter expression error: {exc}")
            return ctx
        if not keep:
            # Drop the message: mark as completed with empty body.
            ctx.body = b""
            ctx.properties["__filter_dropped__"] = True
            ctx.add_trace(node.id, "exit", "message dropped by filter")
        else:
            ctx.add_trace(node.id, "exit", "message passed filter")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "compatible-subset", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "TRUSTED"


register(Filter())
