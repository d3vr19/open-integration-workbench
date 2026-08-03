"""SFTP receiver step (simulated, mocked).

Spec ref: §9.4 (MVP step coverage notes), §9.5 (Mock Adapter Runtime).
The schema (packages/ir-schema/schemas/integration-flow.json) includes
`receiver.sftp` in the enum.

In tests this is mocked via the FlowTest `mocks` block — no real SFTP
connection is made. Production SFTP support is Phase 6 (spec §19 Phase 6).
"""

from __future__ import annotations

from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register


class SftpReceiver(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "receiver.sftp",
            "name": "SFTP Receiver (mocked)",
            "description": "Writes the message body to an SFTP target. In tests, mocked via FlowTest.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "SFTP host (use *.invalid for fixtures)."},
                "port": {"type": "integer", "minimum": 1, "maximum": 65535, "default": 22},
                "path": {"type": "string", "description": "Remote path / filename pattern."},
                "credentialRef": {"type": "string"},
                "fileName": {
                    "type": "string",
                    "description": "Concrete filename; supports ${property.X} interpolation.",
                },
            },
            "required": ["host", "path"],
        }

    def validate(self, node: FlowNode) -> list[str]:
        errors: list[str] = []
        host = node.config.get("host", "")
        if not host:
            errors.append(f"OIW-E001: receiver.sftp node '{node.id}' must specify 'host'")
        # SFTP credentials must use credentialRef, never inline.
        if "password" in node.config:
            errors.append(
                f"OIW-E002: receiver.sftp node '{node.id}' has inline 'password'; use credentialRef"
            )
        return errors

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(
            node.id, "enter", f"SFTP put {node.config.get('host', '')}:{node.config.get('path', '')}"
        )
        host = _interpolate(node.config.get("host", ""), ctx)
        path = _interpolate(node.config.get("path", ""), ctx)
        file_name = _interpolate(node.config.get("fileName", "message.dat"), ctx)

        # Record the outbound SFTP "call" for assertions (analogous to HTTP receiver)
        ctx.record_outbound(
            target=node.id,
            method="PUT",
            url=f"sftp://{host}{path}/{file_name}",
            body=ctx.body,
            headers={"Content-Type": ctx.content_type, "fileName": file_name},
        )

        mock = mocks.get(node.id)
        if mock is not None:
            respond = mock.get("respond", {})
            status = respond.get("status", 200)
            ctx.headers["SFTP_Status"] = str(status)
            ctx.add_trace(node.id, "exit", f"mocked SFTP put status={status}")
        else:
            # No mock — simulate a successful put
            ctx.headers["SFTP_Status"] = "200"
            ctx.add_trace(node.id, "exit", "no mock — simulated successful SFTP put")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {
            "fidelity": "simulated",
            "target_profiles": ["sap-cloud-integration-2026-07"],
            "note": "Mocked in tests via FlowTest. Real SFTP support is Phase 6.",
        }

    def security_classification(self) -> str:
        return "NETWORK"


def _interpolate(value: str, ctx: MessageContext) -> str:
    """Resolve ${property.X} and ${header.Y} placeholders. Spec §7.3 rule 10."""
    if not isinstance(value, str):
        return str(value)
    out = value
    for k, v in ctx.properties.items():
        out = out.replace(f"${{property.{k}}}", str(v))
    for k, v in ctx.headers.items():
        out = out.replace(f"${{header.{k}}}", str(v))
    return out


register(SftpReceiver())
