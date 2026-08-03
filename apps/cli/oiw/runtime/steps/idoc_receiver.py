"""IDoc receiver step (simulated).

Spec ref: §9.4 (`receiver.idoc`), WP-06 Track B Task B-003.
Sends IDoc messages to SAP systems via tRFC.
"""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register

# Known IDoc types (spec §17.1 — validate against this list)
KNOWN_IDOC_TYPES = {
    "ORDERS05",
    "MATMAS05",
    "DEBMAS07",
    "CREMAS07",
    "INVOIC02",
    "DELVRY07",
    "ORDRSP05",
    "CONDTAB",
}


class IDocReceiver(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "receiver.idoc",
            "name": "IDoc Receiver (simulated)",
            "description": "Sends IDoc to SAP via tRFC. Validates type, generates acknowledgment.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "idocType": {"type": "string", "description": "e.g., ORDERS05, MATMAS05"},
                "messageType": {"type": "string"},
                "senderPartnerType": {"type": "string"},
                "senderPartnerNumber": {"type": "string"},
                "receiverPartnerType": {"type": "string"},
                "receiverPartnerNumber": {"type": "string"},
                "credentialRef": {"type": "string"},
            },
            "required": ["idocType"],
        }

    def validate(self, node: FlowNode) -> list[str]:
        errors: list[str] = []
        idoc_type = node.config.get("idocType", "")
        if not idoc_type:
            errors.append(f"OIW-E001: receiver.idoc node '{node.id}' must specify 'idocType'")
        elif idoc_type not in KNOWN_IDOC_TYPES:
            errors.append(f"OIW-W002: receiver.idoc node '{node.id}' has unknown idocType '{idoc_type}'")
        return errors

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        idoc_type = node.config.get("idocType", "")
        ctx.add_trace(node.id, "enter", f"IDoc send type={idoc_type}")

        # Parse IDoc XML if body is XML
        segments = _parse_idoc_segments(ctx.body)
        if segments:
            ctx.headers["IDoc_SegmentCount"] = str(len(segments))
            ctx.add_trace(node.id, "info", f"parsed {len(segments)} IDoc segments")

        # Record outbound call
        ctx.record_outbound(
            target=node.id,
            method="POST",
            url=f"sap-tRFC://{node.config.get('receiverPartnerNumber', 'unknown')}",
            body=ctx.body,
            headers={"IDoc-Type": idoc_type},
        )

        # Use mock if provided
        mock = mocks.get(node.id)
        if mock is not None:
            respond = mock.get("respond", {})
            status = respond.get("status", 200)
            ctx.headers["HTTP_Status"] = str(status)
            ctx.add_trace(node.id, "exit", f"mocked IDoc response status={status}")
        else:
            # Generate IDoc acknowledgment (status record)
            ctx.headers["HTTP_Status"] = "200"
            ack = _generate_idoc_ack(idoc_type, segments)
            ctx.body = ack.encode("utf-8")
            ctx.add_trace(node.id, "exit", "generated IDoc acknowledgment")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "simulated", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "NETWORK"


def _parse_idoc_segments(body: bytes | str) -> list[dict[str, str]]:
    """Parse IDoc XML and extract segment names + fields."""
    try:
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        root = ET.fromstring(body)
        segments = []
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if "Segment" in tag or tag.startswith("E2"):
                segments.append({"name": tag, "fields": dict(elem.attrib)})
        return segments
    except ET.ParseError:
        return []


def _generate_idoc(idoc_type: str, segments: list[dict[str, str]]) -> str:
    """Generate a simple IDoc acknowledgment (status record)."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<IDOC_ACK>
  <STATUS>
    <IDOCTYPE>{idoc_type}</IDOCTYPE>
    <STATUS_CODE>03</STATUS_CODE>
    <SEGMENT_COUNT>{len(segments)}</SEGMENT_COUNT>
    <MESSAGE>IDoc processed successfully</MESSAGE>
  </STATUS>
</IDOC_ACK>"""


_generate_idoc_ack = _generate_idoc  # alias for clarity


register(IDocReceiver())
