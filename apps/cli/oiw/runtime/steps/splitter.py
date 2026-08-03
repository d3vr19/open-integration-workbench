"""Splitter step (bounded).

Spec ref: §9.4 (`splitter.general`, fidelity=simulated, bounded payloads only).
OIW-E003 enforces maxIterations/maxItems; this plugin refuses to execute
without a bound.
"""

from __future__ import annotations

import json
from typing import Any

from ...project import FlowNode
from ..context import ExchangeStatus, MessageContext
from .base import StepPlugin, register


class SplitterGeneral(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "splitter.general",
            "name": "Splitter (bounded)",
            "description": "Splits a message into multiple messages. Bounded payloads only (spec §9.4).",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "XPath or JSONPath expression to split on."},
                "encoding": {"enum": ["xml", "json"], "default": "json"},
                "maxIterations": {"type": "integer", "minimum": 1, "maximum": 10000},
                "maxItems": {"type": "integer", "minimum": 1, "maximum": 10000},
            },
            "anyOf": [{"required": ["maxIterations"]}, {"required": ["maxItems"]}],
        }

    def validate(self, node: FlowNode) -> list[str]:
        errors: list[str] = []
        if not node.config.get("maxIterations") and not node.config.get("maxItems"):
            errors.append(f"OIW-E003: splitter node '{node.id}' must declare maxIterations or maxItems")
        return errors

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(node.id, "enter", "splitting message")
        max_items = node.config.get("maxItems") or node.config.get("maxIterations") or 100
        encoding = node.config.get("encoding", "json")
        expression = node.config.get("expression")

        try:
            if encoding == "json":
                items = self._split_json(ctx.body, expression, max_items)
            else:
                items = self._split_xml(ctx.body, expression, max_items)
        except Exception as exc:
            ctx.exchange_status = ExchangeStatus.FAILED
            ctx.exception = exc
            ctx.add_trace(node.id, "error", f"split failed: {exc}")
            return ctx

        # The prototype does not actually fork the message into N parallel
        # executions (that requires the JVM runtime worker's iterator semantics).
        # Instead, we store the split items as attachments on the context so
        # downstream steps can iterate. DEV-003: full splitter behaviour is
        # Phase 2 work (services/runtime-worker).
        from ..context import Attachment

        ctx.attachments = [
            Attachment(name=f"split-{i}", content_type=f"application/{encoding}", body=item)
            for i, item in enumerate(items)
        ]
        ctx.properties["__splitter_count__"] = len(items)
        ctx.add_trace(node.id, "exit", f"split into {len(items)} item(s)")
        return ctx

    def _split_json(self, body: bytes, expression: str | None, max_items: int) -> list[bytes]:
        data = json.loads(body)
        if not isinstance(data, list):
            data = [data]
        items = data[:max_items]
        return [json.dumps(item).encode("utf-8") for item in items]

    def _split_xml(self, body: bytes, expression: str | None, max_items: int) -> list[bytes]:
        from lxml import etree

        root = etree.fromstring(body)
        # Naive split: each direct child becomes its own document.
        children = list(root)[:max_items]
        out: list[bytes] = []
        for child in children:
            out.append(etree.tostring(child))
        return out

    def compatibility(self) -> dict[str, Any]:
        return {
            "fidelity": "simulated",
            "target_profiles": ["sap-cloud-integration-2026-07"],
            "note": "Prototype stores split items as attachments; full iterator semantics is Phase 2.",
        }

    def security_classification(self) -> str:
        return "SANDBOXED"


register(SplitterGeneral())
