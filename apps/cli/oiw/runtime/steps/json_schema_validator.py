"""JSON Schema validator step.

Spec ref: §9.4 (`validator.json-schema`, fidelity=compatible-subset).
"""

from __future__ import annotations

import json
from typing import Any

import jsonschema

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register


class JsonSchemaValidator(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "validator.json-schema",
            "name": "JSON Schema Validator",
            "description": "Validates the message body against a JSON Schema.",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "schema": {
                    "type": "string",
                    "description": "Path to JSON Schema file under resources/schemas/.",
                },
            },
            "required": ["schema"],
        }

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(node.id, "enter", "validating against JSON Schema")
        schema_path = node.config["schema"]
        resources = ctx.variables.get("__resources__", {})
        schema_bytes = resources.get(schema_path)
        if schema_bytes is None:
            ctx.exchange_status = "FAILED"
            ctx.exception = FileNotFoundError(f"JSON Schema not found: {schema_path}")
            ctx.add_trace(node.id, "error", f"schema not found: {schema_path}")
            return ctx
        try:
            schema = json.loads(schema_bytes)
            body_json = json.loads(ctx.body.decode("utf-8"))
            jsonschema.validate(body_json, schema)
            ctx.add_trace(node.id, "exit", "validation passed")
        except jsonschema.ValidationError as exc:
            ctx.exchange_status = "FAILED"
            ctx.exception = exc
            ctx.add_trace(node.id, "error", f"validation failed: {exc.message}")
        except json.JSONDecodeError as exc:
            ctx.exchange_status = "FAILED"
            ctx.exception = exc
            ctx.add_trace(node.id, "error", f"invalid JSON: {exc}")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "compatible-subset", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "TRUSTED"


register(JsonSchemaValidator())
