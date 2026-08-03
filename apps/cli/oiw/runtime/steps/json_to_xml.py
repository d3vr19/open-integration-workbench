"""JSON-to-XML converter step.

Spec ref: §9.4 (`converter.json-to-xml`, fidelity=compatible-subset).
"""

from __future__ import annotations

import json
import re
from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register


class JsonToXmlConverter(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "converter.json-to-xml",
            "name": "JSON to XML Converter",
            "description": "Converts a JSON message body into a simple XML representation.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "rootElement": {"type": "string", "description": "Name of the root XML element."},
            },
            "required": ["rootElement"],
        }

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(node.id, "enter", "converting JSON to XML")
        try:
            data = json.loads(ctx.body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            ctx.exchange_status = "FAILED"
            ctx.exception = exc
            ctx.add_trace(node.id, "error", f"invalid JSON: {exc}")
            return ctx
        root = node.config.get("rootElement", "Root")
        xml = _to_xml(root, data)
        ctx.body = xml.encode("utf-8")
        ctx.headers["Content-Type"] = "application/xml"
        ctx.add_trace(node.id, "exit", f"converted to XML ({len(ctx.body)} bytes)")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "compatible-subset", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "TRUSTED"


def _to_xml(tag: str, value: Any) -> str:
    """Convert a JSON value to a simple XML representation."""
    safe_tag = _safe_tag(tag)
    if value is None:
        return f"<{safe_tag}/>"
    if isinstance(value, bool):
        return f"<{safe_tag}>{'true' if value else 'false'}</{safe_tag}>"
    if isinstance(value, int | float | str):
        return f"<{safe_tag}>{_escape(str(value))}</{safe_tag}>"
    if isinstance(value, list):
        items = "".join(_to_xml("item", v) for v in value)
        return f"<{safe_tag}>{items}</{safe_tag}>"
    if isinstance(value, dict):
        children = "".join(_to_xml(k, v) for k, v in value.items())
        return f"<{safe_tag}>{children}</{safe_tag}>"
    return f"<{safe_tag}/>"


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_tag(tag: str) -> str:
    """Make a string safe to use as an XML tag name."""
    out = re.sub(r"[^A-Za-z0-9_\-.]", "_", tag)
    if not out or out[0].isdigit():
        out = "_" + out
    return out


register(JsonToXmlConverter())
