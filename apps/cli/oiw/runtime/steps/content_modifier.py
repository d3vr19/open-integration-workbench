"""Content modifier step.

Spec ref: §9.4 (`modifier.content`, fidelity=compatible-subset).

Modifies headers, properties, and/or body of the message.
"""

from __future__ import annotations

from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register


class ContentModifier(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "modifier.content",
            "name": "Content Modifier",
            "description": "Set/replace headers, properties, and/or body.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "headers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "value": {"type": "string"},
                            "action": {"enum": ["set", "remove"], "default": "set"},
                        },
                        "required": ["name"],
                    },
                },
                "properties": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "value": {},
                            "action": {"enum": ["set", "remove"], "default": "set"},
                        },
                        "required": ["name"],
                    },
                },
                "body": {"type": "string"},
            },
        }

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(node.id, "enter", "applying content modifier")
        for header in node.config.get("headers", []) or []:
            name = header["name"]
            action = header.get("action", "set")
            if action == "remove":
                ctx.headers.pop(name, None)
            else:
                value = header.get("value", "")
                ctx.headers[name] = _interpolate(value, ctx)
        for prop in node.config.get("properties", []) or []:
            name = prop["name"]
            action = prop.get("action", "set")
            if action == "remove":
                ctx.properties.pop(name, None)
            else:
                ctx.properties[name] = _interpolate(prop.get("value", ""), ctx)
        if "body" in node.config:
            ctx.body = _interpolate(node.config["body"], ctx).encode("utf-8")
        ctx.add_trace(node.id, "exit", "content modifier applied")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "compatible-subset", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "TRUSTED"


def _interpolate(value: Any, ctx: MessageContext) -> str:
    """Resolve ${header.X}, ${property.Y}, ${body} placeholders.

    Spec §7.3 rule 10: explicit expression language; no implicit evaluation.
    """
    if not isinstance(value, str):
        return str(value)
    out = value
    for k, v in ctx.headers.items():
        out = out.replace(f"${{header.{k}}}", str(v))
    for k, v in ctx.properties.items():
        out = out.replace(f"${{property.{k}}}", str(v))
    out = out.replace("${body}", ctx.body.decode("utf-8", errors="replace"))
    return out


register(ContentModifier())
