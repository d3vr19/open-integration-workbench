"""SOAP sender step (simulated).

Spec ref: §9.4 (`sender.soap`), WP-06 Track B Task B-001.
WP-06 Task B-001: SOAP Sender/Receiver Plugin.

Sends a SOAP request to an external service. In tests, mocked via
the FlowTest `mocks` block like other receivers.
"""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register


class SoapSender(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "sender.soap",
            "name": "SOAP Sender (simulated)",
            "description": "Receives SOAP requests. Parses XML envelope, extracts operation.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "wsdl": {"type": "string", "description": "Path to WSDL file"},
                "operation": {"type": "string", "description": "SOAP operation name"},
                "endpoint": {"type": "string"},
                "credentialRef": {"type": "string"},
            },
            "required": ["endpoint"],
        }

    def validate(self, node: FlowNode) -> list[str]:
        errors: list[str] = []
        if not node.config.get("endpoint"):
            errors.append(f"OIW-E001: sender.soap node '{node.id}' must specify 'endpoint'")
        return errors

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(node.id, "enter", f"SOAP receive at {node.config.get('endpoint', '')}")
        operation = _extract_soap_operation(ctx.body)
        if operation:
            ctx.headers["SOAP_Operation"] = operation
            ctx.add_trace(node.id, "info", f"extracted SOAP operation: {operation}")

        mock = mocks.get(node.id)
        if mock is not None:
            respond = mock.get("respond", {})
            status = respond.get("status", 200)
            body = respond.get("body", "<soap:Envelope><soap:Body/></soap:Envelope>")
            ctx.headers["HTTP_Status"] = str(status)
            ctx.headers["Content-Type"] = "text/xml; charset=utf-8"
            ctx.body = body.encode("utf-8") if isinstance(body, str) else body
            ctx.add_trace(node.id, "exit", f"mocked SOAP response status={status}")
        else:
            ctx.headers["HTTP_Status"] = "200"
            ctx.headers["Content-Type"] = "text/xml; charset=utf-8"
            ctx.add_trace(node.id, "exit", "no mock — simulated 200 OK")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "simulated", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "NETWORK"


def _extract_soap_operation(body: bytes | str) -> str | None:
    """Extract the SOAP operation name from the Body element's first child."""
    try:
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        root = ET.fromstring(body)
        # Strip namespace to find Body
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "Body":
                for child in elem:
                    child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    return child_tag
        return None
    except ET.ParseError:
        return None


register(SoapSender())
