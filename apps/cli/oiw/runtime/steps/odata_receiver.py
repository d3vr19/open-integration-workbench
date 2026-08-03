"""OData V4 receiver step (simulated).

Spec ref: §9.4 (`receiver.odata-v4`), WP-06 Track B Task B-002.
Sends OData requests with pagination support.
"""

from __future__ import annotations

import json
from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register
from .http_receiver import _interpolate


class ODataReceiver(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "receiver.odata-v4",
            "name": "OData V4 Receiver (simulated)",
            "description": "OData V4 request with $filter, $select, $expand, pagination.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "serviceUrl": {"type": "string"},
                "entitySet": {"type": "string"},
                "operation": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
                "pagination": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "pageSize": {"type": "integer"},
                        "maxPages": {"type": "integer"},
                    },
                },
                "credentialRef": {"type": "string"},
                "timeoutSeconds": {"type": "integer"},
            },
            "required": ["serviceUrl", "entitySet", "operation"],
        }

    def validate(self, node: FlowNode) -> list[str]:
        errors: list[str] = []
        if not node.config.get("serviceUrl"):
            errors.append(f"OIW-E001: receiver.odata-v4 node '{node.id}' must specify 'serviceUrl'")
        if not node.config.get("entitySet"):
            errors.append(f"OIW-E001: receiver.odata-v4 node '{node.id}' must specify 'entitySet'")
        if not node.config.get("timeoutSeconds"):
            errors.append(f"OIW-W001: receiver.odata-v4 node '{node.id}' has no timeoutSeconds — recommended")
        return errors

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        service_url = _interpolate(node.config.get("serviceUrl", ""), ctx)
        entity_set = node.config.get("entitySet", "")
        operation = node.config.get("operation", "GET")
        pagination = node.config.get("pagination", {})

        # Build OData URL
        url = f"{service_url.rstrip('/')}/{entity_set}"

        ctx.add_trace(node.id, "enter", f"OData {operation} {url}")

        # Record outbound call
        ctx.record_outbound(
            target=node.id,
            method=operation,
            url=url,
            body=ctx.body,
            headers={"Accept": "application/json"},
        )

        # Use mock if provided
        mock = mocks.get(node.id)
        if mock is not None:
            respond = mock.get("respond", {})
            status = respond.get("status", 200)
            body = respond.get("body", '{"value": []}')
            ctx.headers["HTTP_Status"] = str(status)
            ctx.body = body.encode("utf-8") if isinstance(body, str) else body
            ctx.add_trace(node.id, "exit", f"mocked OData response status={status}")

            # Handle pagination
            if pagination.get("enabled") and isinstance(body, str):
                try:
                    data = json.loads(body)
                    if "@odata.nextLink" in data:
                        max_pages = pagination.get("maxPages", 10)
                        ctx.add_trace(
                            node.id, "info", f"pagination: @odata.nextLink present (maxPages={max_pages})"
                        )
                except json.JSONDecodeError:
                    pass
        else:
            ctx.headers["HTTP_Status"] = "200"
            ctx.body = b'{"value": []}'
            ctx.add_trace(node.id, "exit", "no mock — simulated 200 OK")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "simulated", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "NETWORK"


register(ODataReceiver())
