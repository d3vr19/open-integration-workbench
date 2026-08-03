"""Gather step (bounded).

Spec ref: §9.4 (`gather`, fidelity=simulated).
OIW-W007 warns if no maxItems is configured.
"""

from __future__ import annotations

import json
from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register


class Gather(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "gather",
            "name": "Gather (bounded)",
            "description": "Combines multiple split messages back into one. Bounded (spec §9.4).",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "encoding": {"enum": ["json", "xml"], "default": "json"},
                "maxItems": {"type": "integer", "minimum": 1, "maximum": 10000},
                "combineStrategy": {"enum": ["concat", "merge"], "default": "concat"},
            },
        }

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(node.id, "enter", "gathering messages")
        max_items = node.config.get("maxItems", 1000)
        encoding = node.config.get("encoding", "json")
        strategy = node.config.get("combineStrategy", "concat")

        attachments = ctx.attachments[:max_items]

        if encoding == "json":
            items: list[Any] = []
            for att in attachments:
                try:
                    items.append(json.loads(att.body))
                except Exception:
                    items.append(att.body.decode("utf-8", errors="replace"))
            if strategy == "merge" and all(isinstance(i, dict) for i in items):
                merged: dict[str, Any] = {}
                for i in items:
                    merged.update(i)
                ctx.body = json.dumps(merged).encode("utf-8")
            else:
                ctx.body = json.dumps(items).encode("utf-8")
            ctx.headers["Content-Type"] = "application/json"
        else:
            # XML: concat children inside a <Gather> root
            import contextlib

            from lxml import etree

            root = etree.Element("Gather")
            for att in attachments:
                with contextlib.suppress(Exception):
                    root.append(etree.fromstring(att.body))
            ctx.body = etree.tostring(root, pretty_print=True)
            ctx.headers["Content-Type"] = "application/xml"

        ctx.properties["__gather_count__"] = len(attachments)
        ctx.add_trace(node.id, "exit", f"gathered {len(attachments)} item(s)")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "simulated", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "TRUSTED"


register(Gather())
