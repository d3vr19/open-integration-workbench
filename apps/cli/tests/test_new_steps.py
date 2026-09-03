"""Tests for the new MVP step plugins (splitter, gather, encoder, filter, xml-to-json, sftp)."""

from __future__ import annotations

import base64
import json

from oiw.project import FlowNode
from oiw.runtime.context import MessageContext
from oiw.runtime.steps.base import get_plugin

# ---------------------------------------------------------------------
# splitter.general
# ---------------------------------------------------------------------


def test_splitter_splits_json_array() -> None:
    plugin = get_plugin("splitter.general")
    assert plugin is not None
    node = FlowNode(id="s", type="splitter.general", config={"encoding": "json", "maxItems": 10})
    ctx = MessageContext(body=json.dumps([{"a": 1}, {"a": 2}, {"a": 3}]).encode("utf-8"))
    out = plugin.execute(node, ctx, mocks={})
    assert out.exchange_status == "RUNNING"
    assert out.properties["__splitter_count__"] == 3
    assert len(out.attachments) == 3


def test_splitter_enforces_max_items() -> None:
    plugin = get_plugin("splitter.general")
    node = FlowNode(id="s", type="splitter.general", config={"encoding": "json", "maxItems": 2})
    ctx = MessageContext(body=json.dumps([1, 2, 3, 4, 5]).encode("utf-8"))
    out = plugin.execute(node, ctx, mocks={})
    assert out.properties["__splitter_count__"] == 2


def test_splitter_validation_rejects_unbounded() -> None:
    """Spec §14.1 OIW-E003."""
    plugin = get_plugin("splitter.general")
    node = FlowNode(id="s", type="splitter.general", config={"encoding": "json"})
    errors = plugin.validate(node)
    assert any("OIW-E003" in e for e in errors)


def test_splitter_splits_xml_direct_children() -> None:
    plugin = get_plugin("splitter.general")
    node = FlowNode(id="s", type="splitter.general", config={"encoding": "xml", "maxItems": 10})
    ctx = MessageContext(body=b"<Orders><Order id='1'><item>A</item></Order><Order id='2'><item>B</item></Order></Orders>")
    out = plugin.execute(node, ctx, mocks={})
    assert out.exchange_status == "RUNNING"
    assert out.properties["__splitter_count__"] == 2
    assert len(out.attachments) == 2
    assert b"id=\"1\"" in out.attachments[0].body or b"id='1'" in out.attachments[0].body


def test_splitter_splits_xml_xpath_expression() -> None:
    plugin = get_plugin("splitter.general")
    node = FlowNode(id="s", type="splitter.general", config={"encoding": "xml", "expression": "//Order", "maxItems": 10})
    ctx = MessageContext(body=b"<Batch><Orders><Order id='100'/><Order id='200'/></Orders></Batch>")
    out = plugin.execute(node, ctx, mocks={})
    assert out.properties["__splitter_count__"] == 2
    assert len(out.attachments) == 2


def test_splitter_resolves_property_in_expression() -> None:
    plugin = get_plugin("splitter.general")
    node = FlowNode(
        id="s",
        type="splitter.general",
        config={"encoding": "xml", "expression": "${property.split_xpath}", "maxItems": 5},
    )
    ctx = MessageContext(
        body=b"<Catalog><Book title='B1'/><Book title='B2'/><Mag title='M1'/></Catalog>",
        properties={"split_xpath": "//Book"},
    )
    out = plugin.execute(node, ctx, mocks={})
    assert out.properties["__splitter_count__"] == 2
    assert len(out.attachments) == 2


def test_splitter_splits_json_object_with_expression() -> None:
    plugin = get_plugin("splitter.general")
    node = FlowNode(
        id="s",
        type="splitter.general",
        config={"encoding": "json", "expression": "$.orders", "maxItems": 10},
    )
    ctx = MessageContext(body=b'{"runId":"123","orders":[{"id":"O1"},{"id":"O2"},{"id":"O3"}]}')
    out = plugin.execute(node, ctx, mocks={})
    assert out.properties["__splitter_count__"] == 3
    assert len(out.attachments) == 3


# ---------------------------------------------------------------------
# gather
# ---------------------------------------------------------------------


def test_gather_concat_json() -> None:
    plugin = get_plugin("gather")
    node = FlowNode(
        id="g", type="gather", config={"encoding": "json", "maxItems": 10, "combineStrategy": "concat"}
    )
    from oiw.runtime.context import Attachment

    ctx = MessageContext(body=b"")
    ctx.attachments = [
        Attachment(name="a1", content_type="application/json", body=b'{"x":1}'),
        Attachment(name="a2", content_type="application/json", body=b'{"x":2}'),
    ]
    out = plugin.execute(node, ctx, mocks={})
    gathered = json.loads(out.body)
    assert gathered == [{"x": 1}, {"x": 2}]


def test_gather_merge_json() -> None:
    plugin = get_plugin("gather")
    node = FlowNode(
        id="g", type="gather", config={"encoding": "json", "maxItems": 10, "combineStrategy": "merge"}
    )
    from oiw.runtime.context import Attachment

    ctx = MessageContext(body=b"")
    ctx.attachments = [
        Attachment(name="a1", content_type="application/json", body=b'{"a":1}'),
        Attachment(name="a2", content_type="application/json", body=b'{"b":2}'),
    ]
    out = plugin.execute(node, ctx, mocks={})
    gathered = json.loads(out.body)
    assert gathered == {"a": 1, "b": 2}


def test_gather_xml_elements() -> None:
    plugin = get_plugin("gather")
    node = FlowNode(
        id="g", type="gather", config={"encoding": "xml", "maxItems": 10}
    )
    from oiw.runtime.context import Attachment

    ctx = MessageContext(body=b"")
    ctx.attachments = [
        Attachment(name="a1", content_type="application/xml", body=b'<Item id="1"/>'),
        Attachment(name="a2", content_type="application/xml", body=b'<Item id="2"/>'),
    ]
    out = plugin.execute(node, ctx, mocks={})
    assert out.headers["Content-Type"] == "application/xml"
    assert b"<Gather>" in out.body
    assert b'<Item id="1"/>' in out.body
    assert b'<Item id="2"/>' in out.body


def test_gather_xml_custom_root() -> None:
    plugin = get_plugin("gather")
    node = FlowNode(
        id="g", type="gather", config={"encoding": "xml", "rootElement": "OrderBatch", "maxItems": 10}
    )
    from oiw.runtime.context import Attachment

    ctx = MessageContext(body=b"")
    ctx.attachments = [
        Attachment(name="a1", content_type="application/xml", body=b'<Order id="O1"/>'),
    ]
    out = plugin.execute(node, ctx, mocks={})
    assert b"<OrderBatch>" in out.body
    assert b'<Order id="O1"/>' in out.body


# ---------------------------------------------------------------------
# encoder.base64
# ---------------------------------------------------------------------


def test_base64_encode() -> None:
    plugin = get_plugin("encoder.base64")
    node = FlowNode(id="e", type="encoder.base64", config={"operation": "encode"})
    ctx = MessageContext(body=b"hello world")
    out = plugin.execute(node, ctx, mocks={})
    assert out.body == base64.b64encode(b"hello world")
    assert out.headers["Content-Transfer-Encoding"] == "base64"


def test_base64_decode() -> None:
    plugin = get_plugin("encoder.base64")
    node = FlowNode(id="e", type="encoder.base64", config={"operation": "decode"})
    ctx = MessageContext(body=base64.b64encode(b"hello world"))
    out = plugin.execute(node, ctx, mocks={})
    assert out.body == b"hello world"


def test_base64_decode_invalid_input_fails() -> None:
    plugin = get_plugin("encoder.base64")
    node = FlowNode(id="e", type="encoder.base64", config={"operation": "decode"})
    ctx = MessageContext(body=b"!!!not base64!!!")
    out = plugin.execute(node, ctx, mocks={})
    assert out.exchange_status == "FAILED"


# ---------------------------------------------------------------------
# filter
# ---------------------------------------------------------------------


def test_filter_passes_when_expression_true() -> None:
    plugin = get_plugin("filter")
    node = FlowNode(id="f", type="filter", config={"expression": "true"})
    ctx = MessageContext(body=b"hello")
    out = plugin.execute(node, ctx, mocks={})
    assert out.body == b"hello"
    assert not out.properties.get("__filter_dropped__")


def test_filter_drops_when_expression_false() -> None:
    plugin = get_plugin("filter")
    node = FlowNode(id="f", type="filter", config={"expression": "false"})
    ctx = MessageContext(body=b"hello")
    out = plugin.execute(node, ctx, mocks={})
    assert out.body == b""
    assert out.properties.get("__filter_dropped__") is True


def test_filter_property_expression() -> None:
    plugin = get_plugin("filter")
    node = FlowNode(id="f", type="filter", config={"expression": "${property.region} == 'EU'"})
    ctx = MessageContext(body=b"hello", properties={"region": "EU"})
    out = plugin.execute(node, ctx, mocks={})
    assert out.body == b"hello"

    ctx2 = MessageContext(body=b"hello", properties={"region": "NA"})
    out2 = plugin.execute(node, ctx2, mocks={})
    assert out2.body == b""


# ---------------------------------------------------------------------
# converter.xml-to-json
# ---------------------------------------------------------------------


def test_xml_to_json_simple() -> None:
    plugin = get_plugin("converter.xml-to-json")
    node = FlowNode(id="x", type="converter.xml-to-json", config={})
    ctx = MessageContext(body=b"<Order><id>123</id><total>42.50</total></Order>")
    out = plugin.execute(node, ctx, mocks={})
    data = json.loads(out.body)
    assert data == {"id": "123", "total": "42.50"}
    assert out.headers["Content-Type"] == "application/json"


def test_xml_to_json_with_root_element() -> None:
    plugin = get_plugin("converter.xml-to-json")
    node = FlowNode(id="x", type="converter.xml-to-json", config={"rootElement": "Order"})
    ctx = MessageContext(body=b"<Order><id>123</id></Order>")
    out = plugin.execute(node, ctx, mocks={})
    data = json.loads(out.body)
    assert data == {"Order": {"id": "123"}}


# ---------------------------------------------------------------------
# receiver.sftp
# ---------------------------------------------------------------------


def test_sftp_receiver_records_outbound() -> None:
    plugin = get_plugin("receiver.sftp")
    node = FlowNode(
        id="r",
        type="receiver.sftp",
        config={
            "host": "sftp.example.invalid",
            "port": 22,
            "path": "/upload",
            "fileName": "test.dat",
            "credentialRef": "sftp-client",
        },
    )
    ctx = MessageContext(body=b"hello", properties={"runId": "RUN-1"})
    out = plugin.execute(node, ctx, mocks={})
    assert len(out.outbound_calls) == 1
    call = out.outbound_calls[0]
    assert call["method"] == "PUT"
    assert call["url"] == "sftp://sftp.example.invalid/upload/test.dat"
    assert out.headers["SFTP_Status"] == "200"


def test_sftp_receiver_uses_mock_response() -> None:
    plugin = get_plugin("receiver.sftp")
    node = FlowNode(
        id="r",
        type="receiver.sftp",
        config={"host": "sftp.example.invalid", "path": "/upload", "fileName": "x.dat"},
    )
    ctx = MessageContext(body=b"hello")
    mocks = {"r": {"target": "r", "respond": {"status": 201}}}
    out = plugin.execute(node, ctx, mocks=mocks)
    assert out.headers["SFTP_Status"] == "201"


def test_sftp_receiver_validates_required_fields() -> None:
    plugin = get_plugin("receiver.sftp")
    node = FlowNode(id="r", type="receiver.sftp", config={})
    errors = plugin.validate(node)
    assert any("OIW-E001" in e for e in errors)


def test_sftp_receiver_rejects_inline_password() -> None:
    """Spec §14.1 OIW-E002 — secrets must use credentialRef."""
    plugin = get_plugin("receiver.sftp")
    node = FlowNode(
        id="r",
        type="receiver.sftp",
        config={"host": "sftp.example.invalid", "path": "/x", "password": "supersecret123"},
    )
    errors = plugin.validate(node)
    assert any("OIW-E002" in e for e in errors)


def test_sftp_receiver_interpolates_filename() -> None:
    plugin = get_plugin("receiver.sftp")
    node = FlowNode(
        id="r",
        type="receiver.sftp",
        config={
            "host": "sftp.example.invalid",
            "path": "/upload",
            "fileName": "batch-${property.runId}.b64",
        },
    )
    ctx = MessageContext(body=b"hello", properties={"runId": "RUN-42"})
    out = plugin.execute(node, ctx, mocks={})
    assert out.outbound_calls[0]["url"] == "sftp://sftp.example.invalid/upload/batch-RUN-42.b64"
