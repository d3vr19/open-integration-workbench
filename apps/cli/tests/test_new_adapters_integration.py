"""End-to-end adapter integration tests (WP-06 Task B-006).

Tests that exercise each new adapter in a complete flow simulation.
Uses the step plugin execute() method directly with MessageContext
to verify the full processing chain works.
"""

from __future__ import annotations

from oiw.project import FlowNode
from oiw.runtime.context import MessageContext
from oiw.runtime.steps.base import get_plugin


def _make_node(node_id: str, node_type: str, config: dict) -> FlowNode:
    return FlowNode(id=node_id, type=node_type, config=config, fidelity="simulated")


# ---------------------------------------------------------------------------
# SOAP end-to-end flow
# ---------------------------------------------------------------------------


class TestSoapIntegration:
    def test_soap_flow_end_to_end(self) -> None:
        """HTTPS sender → SOAP receiver (calculator service)."""
        # Step 1: SOAP sender receives a SOAP request
        sender = get_plugin("sender.soap")
        sender_node = _make_node(
            "soap-sender",
            "sender.soap",
            {
                "endpoint": "https://api.example.com/soap",
            },
        )
        ctx = MessageContext(
            body=b"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body><Add><a>1</a><b>2</b></Add></soap:Body>
</soap:Envelope>""",
            headers={},
            properties={},
        )
        ctx = sender.execute(sender_node, ctx, mocks={})
        assert ctx.headers.get("SOAP_Operation") == "Add"

        # Step 2: SOAP receiver sends to external service + gets response
        receiver = get_plugin("receiver.soap")
        recv_node = _make_node(
            "soap-recv",
            "receiver.soap",
            {
                "endpoint": "https://calculator.example.com/soap",
                "operation": "Add",
            },
        )
        mocks = {
            "soap-recv": {
                "respond": {
                    "status": 200,
                    "body": """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body><AddResponse><result>3</result></AddResponse></soap:Body>
</soap:Envelope>""",
                }
            }
        }
        ctx = receiver.execute(recv_node, ctx, mocks=mocks)
        assert ctx.headers.get("Content-Type") == "text/xml; charset=utf-8"
        assert ctx.headers.get("HTTP_Status") == "200"
        assert b"AddResponse" in ctx.body


# ---------------------------------------------------------------------------
# OData end-to-end flow
# ---------------------------------------------------------------------------


class TestODataIntegration:
    def test_odata_flow_with_pagination(self) -> None:
        """HTTP sender → OData receiver (paginated API)."""
        receiver = get_plugin("receiver.odata-v4")
        node = _make_node(
            "odata-recv",
            "receiver.odata-v4",
            {
                "serviceUrl": "https://api.example.com/odata",
                "entitySet": "Orders",
                "operation": "GET",
                "pagination": {"enabled": True, "pageSize": 10, "maxPages": 3},
                "timeoutSeconds": 30,
            },
        )

        mocks = {
            "odata-recv": {
                "respond": {
                    "status": 200,
                    "body": '{"value": [{"id": 1}], "@odata.nextLink": "/Orders?$skip=10"}',
                }
            }
        }

        ctx = MessageContext(body=b"", headers={}, properties={})
        ctx = receiver.execute(node, ctx, mocks=mocks)
        assert ctx.headers.get("HTTP_Status") == "200"
        assert b'"value"' in ctx.body
        # Should have recorded outbound call
        assert len(ctx.outbound_calls) > 0


# ---------------------------------------------------------------------------
# IDoc end-to-end flow
# ---------------------------------------------------------------------------


class TestIDocIntegration:
    def test_idoc_flow_with_transform(self) -> None:
        """Content Modifier → IDoc receiver."""
        # Step 1: Content modifier transforms the body
        modifier = get_plugin("modifier.content")
        mod_node = _make_node(
            "modifier",
            "modifier.content",
            {
                "body": "<IDoc><E1EDK01/><E1EDP01/></IDoc>",
                "headers": [{"name": "Content-Type", "value": "application/xml"}],
            },
        )
        ctx = MessageContext(body=b'{"order": "test"}', headers={}, properties={})
        ctx = modifier.execute(mod_node, ctx, mocks={})

        # Step 2: IDoc receiver processes the XML
        idoc = get_plugin("receiver.idoc")
        idoc_node = _make_node(
            "idoc-recv",
            "receiver.idoc",
            {
                "idocType": "ORDERS05",
                "receiverPartnerNumber": "SAPDEV",
            },
        )
        ctx = idoc.execute(idoc_node, ctx, mocks={})
        assert ctx.headers.get("HTTP_Status") == "200"
        # IDoc acknowledgment generated
        assert b"IDOC_ACK" in ctx.body or b"STATUS" in ctx.body


# ---------------------------------------------------------------------------
# Mail end-to-end flow
# ---------------------------------------------------------------------------


class TestMailIntegration:
    def test_mail_notification_flow(self) -> None:
        """Content Modifier → Mail receiver."""
        # Step 1: Content modifier sets the email body
        modifier = get_plugin("modifier.content")
        mod_node = _make_node(
            "modifier",
            "modifier.content",
            {
                "body": "Order received: #12345",
            },
        )
        ctx = MessageContext(body=b'{"order": 123}', headers={}, properties={})
        ctx = modifier.execute(mod_node, ctx, mocks={})

        # Step 2: Mail receiver sends the email
        mail = get_plugin("receiver.mail")
        mail_node = _make_node(
            "mail-recv",
            "receiver.mail",
            {
                "to": "ops@example.com",
                "subject": "Order Notification",
                "body": "An order was received",
                "smtpHost": "smtp.example.com",
                "smtpPort": 587,
            },
        )
        ctx = mail.execute(mail_node, ctx, mocks={})
        assert ctx.headers.get("SMTP_Status") == "250"
        # Should have recorded outbound SMTP call
        assert len(ctx.outbound_calls) > 0
