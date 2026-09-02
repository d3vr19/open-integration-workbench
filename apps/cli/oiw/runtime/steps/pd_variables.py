"""ProcessDirect + Variables runtime pass-throughs.

These shapes are live-proven on the tenant (exporter grammar mirrored
from operator references: oiw_pd listener = sender.processdirect →
variables.write; RR chains terminate via receiver.processdirect — live
topology law 2026-09-02). The LOCAL engine models them as pass-throughs:
PD send/receive moves the exchange forward (no network — the PD hop is
tenant-internal), variables.write records the value into properties so
assertions can observe it. Fidelity stays 'simulated' honestly — local
pass-through is not semantic equivalence with CPI's process-direct
broker; endpoints are exempt from the real-engine audit by design.
"""

from __future__ import annotations

from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register


class ProcessDirectReceiver(StepPlugin):
    """receiver.processdirect — forward the exchange to a named process.

    Local model: pass-through (records the target address in properties).
    """

    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "receiver.processdirect",
            "name": "ProcessDirect Receiver",
            "description": "Forwards the message to a named process (tenant-internal hop).",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"address": {"type": "string"}},
            "required": ["address"],
        }

    def validate(self, node: FlowNode) -> list[str]:
        return (
            []
            if node.config.get("address")
            else [f"OIW-E001: receiver.processdirect node '{node.id}' must specify 'address'"]
        )

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        address = node.config.get("address", "")
        ctx.add_trace(node.id, "enter", f"ProcessDirect send to {address}")
        ctx.properties["__pd_target__"] = address
        ctx.add_trace(node.id, "exit", "ProcessDirect handed off (local pass-through)")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "simulated", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "SANDBOXED"


class ProcessDirectSender(StepPlugin):
    """sender.processdirect — entrypoint listening on a named process."""

    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "sender.processdirect",
            "name": "ProcessDirect Sender",
            "description": "Starts the flow when a ProcessDirect message arrives.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"address": {"type": "string"}},
            "required": ["address"],
        }

    def validate(self, node: FlowNode) -> list[str]:
        return (
            []
            if node.config.get("address")
            else [f"OIW-E001: sender.processdirect node '{node.id}' must specify 'address'"]
        )

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(node.id, "enter", f"ProcessDirect listen on {node.config.get('address', '')}")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "simulated", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "SANDBOXED"


class VariablesWrite(StepPlugin):
    """variables.write — persist a variable (mirrors oiw_pd's Write Variables)."""

    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "variables.write",
            "name": "Write Variables",
            "description": "Writes a flow variable (e.g. ${body} capture).",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "value": {"type": "string"},
                "valueType": {"enum": ["constant", "expression"], "default": "expression"},
                "scope": {"enum": ["global", "local"], "default": "global"},
            },
            "required": ["name"],
        }

    def validate(self, node: FlowNode) -> list[str]:
        return (
            []
            if node.config.get("name")
            else [f"OIW-E001: variables.write node '{node.id}' must specify 'name'"]
        )

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        import re

        name = node.config.get("name", "var")
        value = str(node.config.get("value", ""))

        # Resolve ${body} / ${property.X} expressions (local model).
        def _resolve(m: re.Match[str]) -> str:
            ref = m.group(1)
            if ref == "body":
                return ctx.body.decode("utf-8", errors="replace")
            if ref.startswith("property."):
                return str(ctx.properties.get(ref[len("property.") :], ""))
            if ref.startswith("header."):
                return str(ctx.headers.get(ref[len("header.") :], ""))
            return m.group(0)

        resolved = re.sub(r"\$\{([^}]+)\}", _resolve, value)
        ctx.properties[f"__variable__.{name}"] = resolved
        ctx.add_trace(node.id, "exit", f"variable {name} written ({len(resolved)} chars)")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "simulated", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "SANDBOXED"


register(ProcessDirectReceiver())
register(ProcessDirectSender())
register(VariablesWrite())
