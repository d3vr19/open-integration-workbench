"""HTTP receiver step (simulated, mocked).

Spec ref: §9.4 (`receiver.http`, fidelity=simulated), §9.5 (Mock Adapter Runtime).
"""

from __future__ import annotations

from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register


class HttpReceiver(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "receiver.http",
            "name": "HTTP Receiver (mocked)",
            "description": "Outbound HTTP call. In tests, mocked via the FlowTest `mocks` block.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"enum": ["GET", "POST", "PUT", "PATCH", "DELETE"], "default": "POST"},
                "credentialRef": {"type": "string"},
                "timeoutSeconds": {"type": "integer", "minimum": 1, "maximum": 300},
            },
            "required": ["url"],
        }

    def validate(self, node: FlowNode) -> list[str]:
        errors: list[str] = []
        url = node.config.get("url", "")
        if not url:
            errors.append(f"OIW-E001: receiver.http node '{node.id}' must specify 'url'")
        elif url.startswith("http://"):
            errors.append(f"OIW-E005: receiver.http node '{node.id}' must use HTTPS")
        return errors

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(
            node.id, "enter", f"HTTP {node.config.get('method', 'POST')} {node.config.get('url', '')}"
        )
        url = _interpolate(node.config.get("url", ""), ctx)
        method = node.config.get("method", "POST")

        # Record the outbound call (spec §9.2 step 4 — capture input/output snapshot per node)
        ctx.record_outbound(
            target=node.id,
            method=method,
            url=url,
            body=ctx.body,
            headers=dict(ctx.headers),
        )

        # Use the mock response if provided
        mock = mocks.get(node.id)
        if mock is not None:
            respond = mock.get("respond", {})
            status = respond.get("status", 200)
            body = respond.get("body", "")
            if "bodyFile" in respond:
                resources = ctx.variables.get("__resources__", {})
                body_bytes = resources.get(respond["bodyFile"], b"")
                body = (
                    body_bytes.decode("utf-8", errors="replace")
                    if isinstance(body_bytes, bytes)
                    else str(body_bytes)
                )
            ctx.headers["HTTP_Status"] = str(status)
            ctx.body = body.encode("utf-8")
            ctx.add_trace(node.id, "exit", f"mocked response status={status}")
        else:
            # No mock — simulate a 200 OK with empty body
            ctx.headers["HTTP_Status"] = "200"
            ctx.body = b""
            ctx.add_trace(node.id, "exit", "no mock — simulated 200 OK")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "simulated", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "NETWORK"


def _interpolate(value: str, ctx: MessageContext) -> str:
    """Resolve ${property.X} placeholders in URLs. Spec §7.3 rule 10."""
    if not isinstance(value, str):
        return str(value)
    out = value
    for k, v in ctx.properties.items():
        out = out.replace(f"${{property.{k}}}", str(v))
    for k, v in ctx.headers.items():
        out = out.replace(f"${{header.{k}}}", str(v))
    return out


register(HttpReceiver())
