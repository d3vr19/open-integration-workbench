"""XSLT transform step.

Spec ref: §9.4 (`transform.xslt`, fidelity=compatible-subset, Saxon-HE XSLT 2.0 subset).

DEV-003: the Python prototype uses lxml (XSLT 1.0). XSLT 2.0 subset support
is Phase 2 work (services/runtime-worker using Saxon-HE on the JVM).
"""

from __future__ import annotations

from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register


class XsltTransform(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "transform.xslt",
            "name": "XSLT Transform (XSLT 1.0; 2.0 in Phase 2)",
            "description": "Applies an XSLT stylesheet to the message body (XML).",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "resource": {"type": "string", "description": "Path to .xsl file under resources/mappings/."},
            },
            "required": ["resource"],
        }

    def validate(self, node: FlowNode) -> list[str]:
        errors: list[str] = []
        if not node.config.get("resource"):
            errors.append(f"OIW-E001: xslt node '{node.id}' must specify 'resource'")
        return errors

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        from lxml import etree

        ctx.add_trace(node.id, "enter", "applying XSLT transform")
        resource_path = node.config["resource"]
        resources = ctx.variables.get("__resources__", {})
        xslt_bytes = resources.get(resource_path)
        if xslt_bytes is None:
            raise FileNotFoundError(f"XSLT resource not found: {resource_path}")

        try:
            xslt_doc = etree.fromstring(
                xslt_bytes if isinstance(xslt_bytes, bytes) else xslt_bytes.encode("utf-8")
            )
            transform = etree.XSLT(xslt_doc)
            source = etree.fromstring(ctx.body)
            result = transform(source)
            ctx.body = str(result).encode("utf-8")
            ctx.headers["Content-Type"] = "application/xml"
            ctx.add_trace(node.id, "exit", "XSLT applied")
        except Exception as exc:
            ctx.exchange_status = "FAILED"
            ctx.exception = exc
            ctx.add_trace(node.id, "error", f"XSLT error: {exc}")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {
            "fidelity": "simulated",
            "target_profiles": ["sap-cloud-integration-2026-07"],
            "note": (
                "Python prototype uses XSLT 1.0 (lxml). XSLT 2.0/3.0 features "
                "are unsupported. Saxon-HE XSLT 2.0 subset via subprocess is "
                "Phase 2 (OW-003). Fidelity downgraded from 'compatible-subset' "
                "to 'simulated' per spec §4.3 — XSLT 1.0-only is not a compatible "
                "subset of real SAP CPI mappings that routinely use XSLT 2.0."
            ),
        }

    def security_classification(self) -> str:
        return "SANDBOXED"


register(XsltTransform())
