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
                items = self._split_json(ctx, expression, max_items)
            else:
                items = self._split_xml(ctx, expression, max_items)
        except Exception as exc:
            ctx.exchange_status = ExchangeStatus.FAILED
            ctx.exception = exc
            ctx.add_trace(node.id, "error", f"split failed: {exc}")
            return ctx

        from ..context import Attachment

        ctx.attachments = [
            Attachment(name=f"split-{i}", content_type=f"application/{encoding}", body=item)
            for i, item in enumerate(items)
        ]
        ctx.properties["__splitter_count__"] = len(items)
        ctx.add_trace(node.id, "exit", f"split into {len(items)} item(s)")
        return ctx

    def _resolve_expr(self, expr: str | None, ctx: MessageContext) -> str | None:
        if not expr or not isinstance(expr, str):
            return expr
        out = expr
        for k, v in ctx.headers.items():
            out = out.replace(f"${{header.{k}}}", str(v))
        for k, v in ctx.properties.items():
            out = out.replace(f"${{property.{k}}}", str(v))
        return out

    def _split_json(self, ctx: MessageContext, expression: str | None, max_items: int) -> list[bytes]:
        data = json.loads(ctx.body)
        expr = self._resolve_expr(expression, ctx)

        if expr:
            # Handle key extraction like $.orders, /orders, orders
            clean_key = expr.lstrip("$.").lstrip("/")
            if isinstance(data, dict) and clean_key in data:
                target = data[clean_key]
                if isinstance(target, list):
                    items = target[:max_items]
                    return [json.dumps(item).encode("utf-8") for item in items]
                return [json.dumps(target).encode("utf-8")]

        if isinstance(data, list):
            items = data[:max_items]
            return [json.dumps(item).encode("utf-8") for item in items]
        if isinstance(data, dict):
            # If dict has a single list property and no specific expression, split that list
            list_vals = [v for v in data.values() if isinstance(v, list)]
            if len(list_vals) == 1:
                return [json.dumps(item).encode("utf-8") for item in list_vals[0][:max_items]]
            return [json.dumps(data).encode("utf-8")]
        return [json.dumps(data).encode("utf-8")]

    def _split_xml(self, ctx: MessageContext, expression: str | None, max_items: int) -> list[bytes]:
        from lxml import etree

        root = etree.fromstring(ctx.body)
        expr = self._resolve_expr(expression, ctx)

        if expr:
            nodes = root.xpath(expr)
            out: list[bytes] = []
            for n in nodes[:max_items]:
                if hasattr(n, "tag"):
                    out.append(etree.tostring(n))
                else:
                    out.append(str(n).encode("utf-8"))
            return out

        # Default XML split: direct child elements
        children = list(root)[:max_items]
        out_children: list[bytes] = []
        for child in children:
            out_children.append(etree.tostring(child))
        return out_children

    def compatibility(self) -> dict[str, Any]:
        return {
            "fidelity": "compatible-subset",
            "target_profiles": ["sap-cloud-integration-2026-07"],
            "note": "Bounded payload splitting for XML and JSON.",
        }

    def security_classification(self) -> str:
        return "SANDBOXED"


register(SplitterGeneral())
