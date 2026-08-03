"""Base64 encoder step.

Spec ref: §9.4 (`encoder.base64`, fidelity=compatible-subset, encode/decode).
"""

from __future__ import annotations

import base64
from typing import Any

from ...project import FlowNode
from ..context import ExchangeStatus, MessageContext
from .base import StepPlugin, register


class Base64Encoder(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "encoder.base64",
            "name": "Base64 Encoder",
            "description": "Encodes or decodes the message body as Base64.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {"enum": ["encode", "decode"], "default": "encode"},
            },
        }

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(node.id, "enter", f"base64 {node.config.get('operation', 'encode')}")
        op = node.config.get("operation", "encode")
        try:
            if op == "encode":
                ctx.body = base64.b64encode(ctx.body)
                ctx.headers["Content-Transfer-Encoding"] = "base64"
            else:
                ctx.body = base64.b64decode(ctx.body)
                ctx.headers.pop("Content-Transfer-Encoding", None)
            ctx.add_trace(node.id, "exit", f"base64 {op} done ({len(ctx.body)} bytes)")
        except Exception as exc:
            ctx.exchange_status = ExchangeStatus.FAILED
            ctx.exception = exc
            ctx.add_trace(node.id, "error", f"base64 {op} failed: {exc}")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "compatible-subset", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "TRUSTED"


register(Base64Encoder())
