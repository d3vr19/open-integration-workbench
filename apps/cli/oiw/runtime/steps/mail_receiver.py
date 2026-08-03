"""Mail (SMTP) receiver step (simulated).

Spec ref: §9.4 (`receiver.mail`), WP-06 Track B Task B-004.
Sends email via SMTP. In tests, mocked via FlowTest.
"""

from __future__ import annotations

from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register


class MailReceiver(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "receiver.mail",
            "name": "Mail Receiver (simulated)",
            "description": "Sends email via SMTP. Supports HTML + plain text, attachments.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Comma-separated recipient list"},
                "cc": {"type": "string"},
                "bcc": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "Email body (plain text or HTML)"},
                "isHtml": {"type": "boolean", "default": False},
                "from": {"type": "string"},
                "credentialRef": {"type": "string", "description": "SMTP credential ref"},
                "smtpHost": {"type": "string"},
                "smtpPort": {"type": "integer", "default": 587},
            },
            "required": ["to", "subject"],
        }

    def validate(self, node: FlowNode) -> list[str]:
        errors: list[str] = []
        if not node.config.get("to"):
            errors.append(f"OIW-E001: receiver.mail node '{node.id}' must specify 'to'")
        if not node.config.get("subject"):
            errors.append(f"OIW-E001: receiver.mail node '{node.id}' must specify 'subject'")
        return errors

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        to = node.config.get("to", "")
        subject = node.config.get("subject", "")
        ctx.add_trace(node.id, "enter", f"Mail send to={to} subject={subject}")

        # Record outbound call
        ctx.record_outbound(
            target=node.id,
            method="SMTP",
            url=f"smtp://{node.config.get('smtpHost', 'localhost')}:{node.config.get('smtpPort', 587)}",
            body=node.config.get("body", "").encode("utf-8")
            if isinstance(node.config.get("body"), str)
            else ctx.body,
            headers={"To": to, "Subject": subject, "From": node.config.get("from", "")},
        )

        # Use mock if provided
        mock = mocks.get(node.id)
        if mock is not None:
            respond = mock.get("respond", {})
            status = respond.get("status", 250)  # 250 OK is SMTP success
            ctx.headers["SMTP_Status"] = str(status)
            ctx.add_trace(node.id, "exit", f"mocked SMTP response status={status}")
        else:
            ctx.headers["SMTP_Status"] = "250"
            ctx.add_trace(node.id, "exit", "no mock — simulated 250 OK")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "simulated", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "NETWORK"


register(MailReceiver())
