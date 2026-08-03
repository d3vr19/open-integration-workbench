"""XML-to-JSON converter step.

Spec ref: §9.4 (`converter.xml-to-json`, fidelity=compatible-subset).
"""

from __future__ import annotations

import json
from typing import Any

from ...project import FlowNode
from ..context import ExchangeStatus, MessageContext
from .base import StepPlugin, register


class XmlToJsonConverter(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "converter.xml-to-json",
            "name": "XML to JSON Converter",
            "description": "Converts a simple XML message body into JSON.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "rootElement": {"type": "string", "description": "Optional: wrap output under this key."},
            },
        }

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(node.id, "enter", "converting XML to JSON")
        try:
            from lxml import etree

            root = etree.fromstring(ctx.body)
            data = _element_to_dict(root)
            if "rootElement" in node.config:
                data = {node.config["rootElement"]: data}
            ctx.body = json.dumps(data).encode("utf-8")
            ctx.headers["Content-Type"] = "application/json"
            ctx.add_trace(node.id, "exit", f"converted to JSON ({len(ctx.body)} bytes)")
        except Exception as exc:
            ctx.exchange_status = ExchangeStatus.FAILED
            ctx.exception = exc
            ctx.add_trace(node.id, "error", f"XML-to-JSON error: {exc}")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "compatible-subset", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "TRUSTED"


def _element_to_dict(elem) -> Any:
    """Recursively convert an lxml element to a dict."""
    children = list(elem)
    if not children:
        return (elem.text or "").strip()
    result: dict[str, Any] = {}
    for child in children:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        value = _element_to_dict(child)
        if tag in result:
            if not isinstance(result[tag], list):
                result[tag] = [result[tag]]
            result[tag].append(value)
        else:
            result[tag] = value
    return result


register(XmlToJsonConverter())
