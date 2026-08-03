"""Log message step.

Spec ref: §9.4 (`log.message`, fidelity=compatible-subset, structured output).
"""

from __future__ import annotations

from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register


class LogMessage(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "log.message",
            "name": "Log Message",
            "description": "Emits a structured log entry.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "level": {"enum": ["INFO", "WARN", "ERROR", "DEBUG"], "default": "INFO"},
                "message": {"type": "string"},
            },
            "required": ["message"],
        }

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        level = node.config.get("level", "INFO")
        message = node.config.get("message", "")
        ctx.add_trace(node.id, "exit", f"[{level}] {message}")
        # Sensitive header redaction already done by MessageContext.redacted_headers
        # (spec §9.2 step 9, §14.1 OIW-W004).
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "compatible-subset", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "TRUSTED"


register(LogMessage())
