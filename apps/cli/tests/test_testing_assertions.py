"""Unit tests for FlowTest assertion types (WP-10 H11).

Acceptance:
1. `outbound.header.equals` — target, name, equals — asserts an outbound mock
   call's request header (works in both engines).
2. `property.contains` — substring assertion on an exchange property.
3. Schema validation accepts both new types.
4. Unknown assertion types keep failing loudly.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from oiw.runtime.context import MessageContext
from oiw.testing import _check_assertion


class TestAssertions:
    def test_outbound_header_equals_success(self) -> None:
        ctx = MessageContext(body=b"")
        ctx.record_outbound(
            target="mock-http",
            method="POST",
            url="https://example.com/api",
            body=b"{}",
            headers={"Content-Type": "application/json", "X-Custom-Id": "12345"},
        )
        assertion = {
            "type": "outbound.header.equals",
            "target": "mock-http",
            "name": "Content-Type",
            "equals": "application/json",
        }
        ok, msg = _check_assertion(assertion, ctx, MagicMock())
        assert ok is True
        assert msg == ""

    def test_outbound_header_equals_case_insensitive_name(self) -> None:
        ctx = MessageContext(body=b"")
        ctx.record_outbound(
            target="mock-http",
            method="POST",
            url="https://example.com/api",
            body=b"{}",
            headers={"content-type": "application/json"},
        )
        assertion = {
            "type": "outbound.header.equals",
            "target": "mock-http",
            "name": "Content-Type",
            "equals": "application/json",
        }
        ok, msg = _check_assertion(assertion, ctx, MagicMock())
        assert ok is True
        assert msg == ""

    def test_outbound_header_equals_mismatch_value(self) -> None:
        ctx = MessageContext(body=b"")
        ctx.record_outbound(
            target="mock-http",
            method="POST",
            url="https://example.com/api",
            body=b"{}",
            headers={"Content-Type": "application/json"},
        )
        assertion = {
            "type": "outbound.header.equals",
            "target": "mock-http",
            "name": "Content-Type",
            "equals": "application/xml",
        }
        ok, msg = _check_assertion(assertion, ctx, MagicMock())
        assert ok is False
        assert "expected 'application/xml', got 'application/json'" in msg

    def test_outbound_header_equals_missing_target(self) -> None:
        ctx = MessageContext(body=b"")
        assertion = {
            "type": "outbound.header.equals",
            "target": "nonexistent-target",
            "name": "Content-Type",
            "equals": "application/json",
        }
        ok, msg = _check_assertion(assertion, ctx, MagicMock())
        assert ok is False
        assert "no outbound call recorded for target 'nonexistent-target'" in msg

    def test_property_contains_success(self) -> None:
        ctx = MessageContext(body=b"")
        ctx.properties["trackingCode"] = "TRK-2026-CONFIRMED-99"
        assertion = {
            "type": "property.contains",
            "name": "trackingCode",
            "contains": "CONFIRMED",
        }
        ok, msg = _check_assertion(assertion, ctx, MagicMock())
        assert ok is True
        assert msg == ""

    def test_property_contains_mismatch(self) -> None:
        ctx = MessageContext(body=b"")
        ctx.properties["trackingCode"] = "TRK-2026-REJECTED-99"
        assertion = {
            "type": "property.contains",
            "name": "trackingCode",
            "contains": "CONFIRMED",
        }
        ok, msg = _check_assertion(assertion, ctx, MagicMock())
        assert ok is False
        assert "does not contain: 'CONFIRMED'" in msg

    def test_property_contains_missing_property(self) -> None:
        ctx = MessageContext(body=b"")
        assertion = {
            "type": "property.contains",
            "name": "missingProp",
            "contains": "val",
        }
        ok, msg = _check_assertion(assertion, ctx, MagicMock())
        assert ok is False
        assert "property 'missingProp' not found" in msg

    def test_unknown_assertion_type_fails_loudly(self) -> None:
        ctx = MessageContext(body=b"")
        assertion = {"type": "unsupported.assertion.custom"}
        ok, msg = _check_assertion(assertion, ctx, MagicMock())
        assert ok is False
        assert "unknown assertion type: unsupported.assertion.custom" in msg
