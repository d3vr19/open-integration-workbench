"""HTTP sender step (entrypoint).

Spec ref: §9.4 (`sender.http`, fidelity=simulated, WireMock-backed).

In the Python prototype we don't actually open a socket — the entrypoint
simply seeds the MessageContext with the inbound message provided by the
test harness.
"""

from __future__ import annotations

from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register


class HttpSender(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "sender.http",
            "name": "HTTP Sender",
            "description": "Inbound HTTP entrypoint. Simulated: the test harness provides the request body and headers.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "methods": {"type": "array", "items": {"type": "string"}},
                "credentialRef": {"type": "string"},
            },
            "required": ["path"],
        }

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        # The sender is the entrypoint — body/headers come from the test input.
        ctx.add_trace(
            node.id, "enter", f"HTTP {node.config.get('methods', ['POST'])[0]} {node.config.get('path', '/')}"
        )
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "simulated", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "TRUSTED"


register(HttpSender())
