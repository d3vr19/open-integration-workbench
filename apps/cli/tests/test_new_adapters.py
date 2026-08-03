"""Tests for new adapter plugins (WP-06 Track B Tasks B-001 to B-004).

Covers SOAP, OData, IDoc, and Mail adapter plugins.
"""

from __future__ import annotations

from oiw.project import FlowNode
from oiw.runtime.context import MessageContext
from oiw.runtime.steps.base import all_plugins, get_plugin

# ---------------------------------------------------------------------------
# Plugin registration tests
# ---------------------------------------------------------------------------


class TestPluginRegistration:
    def test_all_new_plugins_registered(self) -> None:
        """All 4 new adapter plugins are registered."""
        plugins = all_plugins()
        assert "sender.soap" in plugins
        assert "receiver.soap" in plugins
        assert "receiver.odata-v4" in plugins
        assert "receiver.idoc" in plugins
        assert "receiver.mail" in plugins

    def test_plugin_descriptors(self) -> None:
        """Each plugin has a proper descriptor."""
        for type_id in [
            "sender.soap",
            "receiver.soap",
            "receiver.odata-v4",
            "receiver.idoc",
            "receiver.mail",
        ]:
            plugin = get_plugin(type_id)
            assert plugin is not None
            desc = plugin.descriptor()
            assert desc["type"] == type_id
            assert desc["name"]
            assert desc["description"]

    def test_config_schemas_valid(self) -> None:
        """Each plugin has a valid config schema."""
        for type_id in [
            "sender.soap",
            "receiver.soap",
            "receiver.odata-v4",
            "receiver.idoc",
            "receiver.mail",
        ]:
            plugin = get_plugin(type_id)
            schema = plugin.config_schema()
            assert schema["type"] == "object"
            assert "properties" in schema
            assert "required" in schema

    def test_all_adapters_are_network_classification(self) -> None:
        """All adapter plugins have NETWORK security classification."""
        for type_id in [
            "sender.soap",
            "receiver.soap",
            "receiver.odata-v4",
            "receiver.idoc",
            "receiver.mail",
        ]:
            plugin = get_plugin(type_id)
            assert plugin.security_classification() == "NETWORK"


# ---------------------------------------------------------------------------
# SOAP tests (Task B-001)
# ---------------------------------------------------------------------------


class TestSoapSender:
    def _make_node(self, **config) -> FlowNode:
        return FlowNode(id="soap-sender", type="sender.soap", config=config, fidelity="simulated")

    def test_validates_endpoint_required(self) -> None:
        node = self._make_node()
        errors = get_plugin("sender.soap").validate(node)
        assert any("endpoint" in e for e in errors)

    def test_extracts_soap_operation(self) -> None:
        """SOAP sender parses envelope and extracts operation name."""
        plugin = get_plugin("sender.soap")
        node = self._make_node(endpoint="https://example.com/soap")
        ctx = MessageContext(
            body=b"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <Add><a>1</a><b>2</b></Add>
  </soap:Body>
</soap:Envelope>""",
            headers={},
            properties={},
        )
        ctx = plugin.execute(node, ctx, mocks={})
        assert ctx.headers.get("SOAP_Operation") == "Add"

    def test_mock_response(self) -> None:
        """SOAP sender uses mock response when provided."""
        plugin = get_plugin("sender.soap")
        node = self._make_node(endpoint="https://example.com/soap")
        ctx = MessageContext(body=b"<soap:Envelope/>", headers={}, properties={})
        mocks = {"soap-sender": {"respond": {"status": 500, "body": "<error/>"}}}
        ctx = plugin.execute(node, ctx, mocks=mocks)
        assert ctx.headers["HTTP_Status"] == "500"
        assert b"<error/>" in ctx.body


class TestSoapReceiver:
    def _make_node(self, **config) -> FlowNode:
        defaults = {"endpoint": "https://example.com/soap", "operation": "Add"}
        defaults.update(config)
        return FlowNode(id="soap-recv", type="receiver.soap", config=defaults, fidelity="simulated")

    def test_validates_endpoint_and_operation(self) -> None:
        node = FlowNode(id="x", type="receiver.soap", config={}, fidelity="simulated")
        errors = get_plugin("receiver.soap").validate(node)
        assert len(errors) >= 2  # endpoint + operation

    def test_generates_soap_envelope(self) -> None:
        """SOAP receiver generates a valid SOAP response envelope."""
        plugin = get_plugin("receiver.soap")
        node = self._make_node()
        ctx = MessageContext(body=b"request", headers={}, properties={})
        ctx = plugin.execute(node, ctx, mocks={})
        assert ctx.headers["Content-Type"] == "text/xml; charset=utf-8"
        assert b"AddResponse" in ctx.body or b"Envelope" in ctx.body


# ---------------------------------------------------------------------------
# OData tests (Task B-002)
# ---------------------------------------------------------------------------


class TestODataReceiver:
    def _make_node(self, **config) -> FlowNode:
        defaults = {
            "serviceUrl": "https://api.example.com/odata",
            "entitySet": "Orders",
            "operation": "GET",
        }
        defaults.update(config)
        return FlowNode(id="odata-recv", type="receiver.odata-v4", config=defaults, fidelity="simulated")

    def test_validates_required_fields(self) -> None:
        node = FlowNode(id="x", type="receiver.odata-v4", config={}, fidelity="simulated")
        errors = get_plugin("receiver.odata-v4").validate(node)
        assert any("serviceUrl" in e for e in errors)
        assert any("entitySet" in e for e in errors)

    def test_warns_on_missing_timeout(self) -> None:
        """OData receiver without timeout → OIW-W001 warning."""
        node = self._make_node()
        errors = get_plugin("receiver.odata-v4").validate(node)
        assert any("OIW-W001" in e for e in errors)

    def test_mock_response(self) -> None:
        """OData receiver uses mock response."""
        plugin = get_plugin("receiver.odata-v4")
        node = self._make_node(pagination={"enabled": True, "maxPages": 3})
        ctx = MessageContext(body=b"", headers={}, properties={})
        mocks = {
            "odata-recv": {
                "respond": {
                    "status": 200,
                    "body": '{"value": [], "@odata.nextLink": "/Orders?$skip=10"}',
                }
            }
        }
        ctx = plugin.execute(node, ctx, mocks=mocks)
        assert ctx.headers["HTTP_Status"] == "200"
        assert b'"value"' in ctx.body

    def test_default_response_empty(self) -> None:
        """OData receiver without mock returns empty value array."""
        plugin = get_plugin("receiver.odata-v4")
        node = self._make_node()
        ctx = MessageContext(body=b"", headers={}, properties={})
        ctx = plugin.execute(node, ctx, mocks={})
        assert b'"value": []' in ctx.body


# ---------------------------------------------------------------------------
# IDoc tests (Task B-003)
# ---------------------------------------------------------------------------


class TestIDocReceiver:
    def _make_node(self, **config) -> FlowNode:
        defaults = {"idocType": "ORDERS05"}
        defaults.update(config)
        return FlowNode(id="idoc-recv", type="receiver.idoc", config=defaults, fidelity="simulated")

    def test_validates_idoc_type_required(self) -> None:
        node = FlowNode(id="x", type="receiver.idoc", config={}, fidelity="simulated")
        errors = get_plugin("receiver.idoc").validate(node)
        assert any("idocType" in e for e in errors)

    def test_warns_on_unknown_idoc_type(self) -> None:
        """Unknown IDoc type → OIW-W002 warning."""
        node = self._make_node(idocType="UNKNOWN99")
        errors = get_plugin("receiver.idoc").validate(node)
        assert any("OIW-W002" in e for e in errors)

    def test_known_idoc_type_accepted(self) -> None:
        """Known IDoc types (ORDERS05, MATMAS05) pass validation."""
        for idoc_type in ["ORDERS05", "MATMAS05", "DEBMAS07", "CREMAS07"]:
            node = self._make_node(idocType=idoc_type)
            errors = get_plugin("receiver.idoc").validate(node)
            assert not any("OIW-W002" in e for e in errors)

    def test_generates_acknowledgment(self) -> None:
        """IDoc receiver generates acknowledgment."""
        plugin = get_plugin("receiver.idoc")
        node = self._make_node()
        ctx = MessageContext(body=b"<IDoc/>", headers={}, properties={})
        ctx = plugin.execute(node, ctx, mocks={})
        assert ctx.headers["HTTP_Status"] == "200"
        assert b"IDOC_ACK" in ctx.body or b"STATUS" in ctx.body


# ---------------------------------------------------------------------------
# Mail tests (Task B-004)
# ---------------------------------------------------------------------------


class TestMailReceiver:
    def _make_node(self, **config) -> FlowNode:
        defaults = {"to": "user@example.com", "subject": "Test"}
        defaults.update(config)
        return FlowNode(id="mail-recv", type="receiver.mail", config=defaults, fidelity="simulated")

    def test_validates_to_and_subject(self) -> None:
        node = FlowNode(id="x", type="receiver.mail", config={}, fidelity="simulated")
        errors = get_plugin("receiver.mail").validate(node)
        assert any("'to'" in e for e in errors)
        assert any("'subject'" in e for e in errors)

    def test_sends_email(self) -> None:
        """Mail receiver records outbound call."""
        plugin = get_plugin("receiver.mail")
        node = self._make_node(body="Hello", smtpHost="smtp.example.com")
        ctx = MessageContext(body=b"", headers={}, properties={})
        ctx = plugin.execute(node, ctx, mocks={})
        assert ctx.headers["SMTP_Status"] == "250"
        assert len(ctx.outbound_calls) > 0

    def test_mock_response(self) -> None:
        """Mail receiver uses mock SMTP response."""
        plugin = get_plugin("receiver.mail")
        node = self._make_node()
        ctx = MessageContext(body=b"", headers={}, properties={})
        mocks = {"mail-recv": {"respond": {"status": 550}}}
        ctx = plugin.execute(node, ctx, mocks=mocks)
        assert ctx.headers["SMTP_Status"] == "550"
