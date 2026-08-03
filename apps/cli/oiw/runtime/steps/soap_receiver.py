"""SOAP receiver step (simulated).

Spec ref: §9.4 (`receiver.soap`), WP-06 Track B Task B-001.
Sends a SOAP request to an external service. Generates SOAP envelope.
"""

from __future__ import annotations

from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register
from .http_receiver import _interpolate


class SoapReceiver(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "receiver.soap",
            "name": "SOAP Receiver (simulated)",
            "description": "Sends SOAP request to external service. Generates envelope.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "endpoint": {"type": "string"},
                "operation": {"type": "string"},
                "soapAction": {"type": "string"},
                "credentialRef": {"type": "string"},
                "timeoutSeconds": {"type": "integer", "minimum": 1, "maximum": 300},
            },
            "required": ["endpoint", "operation"],
        }

    def validate(self, node: FlowNode) -> list[str]:
        errors: list[str] = []
        if not node.config.get("endpoint"):
            errors.append(f"OIW-E001: receiver.soap node '{node.id}' must specify 'endpoint'")
        if not node.config.get("operation"):
            errors.append(f"OIW-E001: receiver.soap node '{node.id}' must specify 'operation'")
        return errors

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        endpoint = _interpolate(node.config.get("endpoint", ""), ctx)
        operation = node.config.get("operation", "")
        ctx.add_trace(node.id, "enter", f"SOAP {operation} → {endpoint}")

        # Record outbound call
        ctx.record_outbound(
            target=node.id,
            method="POST",
            url=endpoint,
            body=ctx.body,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": node.config.get("soapAction", ""),
            },
        )

        # Use mock if provided
        mock = mocks.get(node.id)
        if mock is not None:
            respond = mock.get("respond", {})
            status = respond.get("status", 200)
            body = respond.get("body", _default_soap_response(operation))
            ctx.headers["HTTP_Status"] = str(status)
            ctx.headers["Content-Type"] = "text/xml; charset=utf-8"
            ctx.body = body.encode("utf-8") if isinstance(body, str) else body
            ctx.add_trace(node.id, "exit", f"mocked SOAP response status={status}")
        else:
            ctx.headers["HTTP_Status"] = "200"
            ctx.headers["Content-Type"] = "text/xml; charset=utf-8"
            ctx.body = _default_soap_response(operation).encode("utf-8")
            ctx.add_trace(node.id, "exit", "no mock — simulated 200 OK")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "simulated", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "NETWORK"


def _default_soap_response(operation: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <{operation}Response/>
  </soap:Body>
</soap:Envelope>"""


register(SoapReceiver())
