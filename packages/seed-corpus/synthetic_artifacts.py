"""Synthetic adapter artifacts for seed corpus (WP-06 Task B-007).

Creates synthetic integration flow artifacts that use the new adapter
families (SOAP, OData, IDoc, Mail) to diversify the seed corpus.

Each artifact is a flow.yaml + diagram.json + tests/ that exercises
a specific adapter. The artifacts are ingested through the standard
pipeline and synthesized into expert trajectories.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


# Template for a minimal flow.yaml
def _make_flow_yaml(
    flow_id: str,
    flow_name: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> str:
    """Generate a flow.yaml string."""
    flow = {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationFlow",
        "metadata": {"id": flow_id, "name": flow_name, "version": 1, "labels": {}},
        "spec": {
            "entrypoints": [],
            "nodes": nodes,
            "edges": edges,
            "extensions": {},
        },
    }
    return yaml.safe_dump(
        flow, sort_keys=True, default_flow_style=False, allow_unicode=True
    )


def _make_node(node_id: str, node_type: str, config: dict[str, Any]) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "config": config, "fidelity": "simulated"}


def _make_test(test_name: str, flow_id: str) -> str:
    """Generate a minimal FlowTest YAML."""
    test = {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "FlowTest",
        "metadata": {"name": test_name, "flow": flow_id},
        "spec": {
            "input": {"bodyInline": "{}"},
            "assertions": [{"type": "exchange.status", "equals": "COMPLETED"}],
            "mocks": [],
        },
    }
    return yaml.safe_dump(
        test, sort_keys=True, default_flow_style=False, allow_unicode=True
    )


# Artifact generators — each creates a different adapter pattern


def make_soap_calculator_flow() -> tuple[str, str, str]:
    """SOAP calculator flow: HTTP sender → SOAP receiver."""
    flow_id = "soap-calculator"
    flow_name = "SOAP Calculator Service"
    nodes = [
        _make_node(
            "sender", "sender.http", {"path": "/calculate", "methods": ["POST"]}
        ),
        _make_node(
            "soap-recv",
            "receiver.soap",
            {
                "endpoint": "https://calculator.example.com/soap",
                "operation": "Add",
                "soapAction": "http://example.com/Add",
                "timeoutSeconds": 30,
            },
        ),
    ]
    edges = [{"from": "sender", "to": "soap-recv"}]
    return flow_id, flow_name, _make_flow_yaml(flow_id, flow_name, nodes, edges)


def make_odata_pagination_flow() -> tuple[str, str, str]:
    """OData paginated query flow: HTTP sender → OData receiver."""
    flow_id = "odata-orders"
    flow_name = "OData Orders with Pagination"
    nodes = [
        _make_node("sender", "sender.http", {"path": "/orders", "methods": ["GET"]}),
        _make_node(
            "odata-recv",
            "receiver.odata-v4",
            {
                "serviceUrl": "https://api.example.com/odata",
                "entitySet": "Orders",
                "operation": "GET",
                "pagination": {"enabled": True, "pageSize": 50, "maxPages": 10},
                "timeoutSeconds": 60,
            },
        ),
    ]
    edges = [{"from": "sender", "to": "odata-recv"}]
    return flow_id, flow_name, _make_flow_yaml(flow_id, flow_name, nodes, edges)


def make_idoc_orders_flow() -> tuple[str, str, str]:
    """IDoc orders flow: HTTP sender → Content Modifier → IDoc receiver."""
    flow_id = "idoc-orders05"
    flow_name = "IDoc ORDERS05 Sender"
    nodes = [
        _make_node(
            "sender", "sender.http", {"path": "/send-idoc", "methods": ["POST"]}
        ),
        _make_node(
            "modifier",
            "modifier.content",
            {
                "headers": [{"name": "Content-Type", "value": "application/xml"}],
                "body": "<IDoc><E1EDK01/><E1EDP01/></IDoc>",
            },
        ),
        _make_node(
            "idoc-recv",
            "receiver.idoc",
            {
                "idocType": "ORDERS05",
                "messageType": "ORDERS",
                "receiverPartnerNumber": "SAPDEV",
                "receiverPartnerType": "LS",
            },
        ),
    ]
    edges = [
        {"from": "sender", "to": "modifier"},
        {"from": "modifier", "to": "idoc-recv"},
    ]
    return flow_id, flow_name, _make_flow_yaml(flow_id, flow_name, nodes, edges)


def make_mail_notification_flow() -> tuple[str, str, str]:
    """Mail notification flow: HTTP sender → Content Modifier → Mail receiver."""
    flow_id = "mail-notification"
    flow_name = "Email Notification on Order"
    nodes = [
        _make_node("sender", "sender.http", {"path": "/notify", "methods": ["POST"]}),
        _make_node(
            "modifier",
            "modifier.content",
            {
                "headers": [{"name": "Subject", "value": "Order Received"}],
                "body": "A new order has been received and processed.",
            },
        ),
        _make_node(
            "mail-recv",
            "receiver.mail",
            {
                "to": "ops@example.com",
                "subject": "Order Notification",
                "body": "Order processed successfully",
                "smtpHost": "smtp.example.com",
                "smtpPort": 587,
            },
        ),
    ]
    edges = [
        {"from": "sender", "to": "modifier"},
        {"from": "modifier", "to": "mail-recv"},
    ]
    return flow_id, flow_name, _make_flow_yaml(flow_id, flow_name, nodes, edges)


def make_soap_to_http_flow() -> tuple[str, str, str]:
    """SOAP-to-HTTP flow: SOAP sender → HTTP receiver."""
    flow_id = "soap-to-http"
    flow_name = "SOAP to HTTP Bridge"
    nodes = [
        _make_node(
            "soap-sender",
            "sender.soap",
            {
                "endpoint": "https://api.example.com/soap",
                "operation": "ProcessOrder",
            },
        ),
        _make_node(
            "http-recv",
            "receiver.http",
            {
                "url": "https://backend.example.com/api/orders",
                "method": "POST",
                "timeoutSeconds": 30,
            },
        ),
    ]
    edges = [{"from": "soap-sender", "to": "http-recv"}]
    return flow_id, flow_name, _make_flow_yaml(flow_id, flow_name, nodes, edges)


def make_odata_to_idoc_flow() -> tuple[str, str, str]:
    """OData-to-IDoc flow: OData receiver → IDoc receiver."""
    flow_id = "odata-to-idoc"
    flow_name = "OData Query to IDoc"
    nodes = [
        _make_node("sender", "sender.http", {"path": "/sync", "methods": ["POST"]}),
        _make_node(
            "odata-recv",
            "receiver.odata-v4",
            {
                "serviceUrl": "https://api.example.com/odata",
                "entitySet": "Products",
                "operation": "GET",
                "timeoutSeconds": 30,
            },
        ),
        _make_node(
            "idoc-recv",
            "receiver.idoc",
            {
                "idocType": "MATMAS05",
                "messageType": "MATMAS",
                "receiverPartnerNumber": "SAPDEV",
            },
        ),
    ]
    edges = [
        {"from": "sender", "to": "odata-recv"},
        {"from": "odata-recv", "to": "idoc-recv"},
    ]
    return flow_id, flow_name, _make_flow_yaml(flow_id, flow_name, nodes, edges)


def make_idoc_to_mail_flow() -> tuple[str, str, str]:
    """IDoc-to-Mail flow: HTTP sender → IDoc receiver → Mail notification."""
    flow_id = "idoc-to-mail"
    flow_name = "IDoc Processing with Mail Alert"
    nodes = [
        _make_node("sender", "sender.http", {"path": "/process", "methods": ["POST"]}),
        _make_node(
            "idoc-recv",
            "receiver.idoc",
            {
                "idocType": "DEBMAS07",
                "messageType": "DEBMAS",
                "receiverPartnerNumber": "SAPDEV",
            },
        ),
        _make_node(
            "mail-recv",
            "receiver.mail",
            {
                "to": "alerts@example.com",
                "subject": "IDoc Processed",
                "body": "Customer master IDoc was processed successfully.",
                "smtpHost": "smtp.example.com",
                "smtpPort": 587,
            },
        ),
    ]
    edges = [
        {"from": "sender", "to": "idoc-recv"},
        {"from": "idoc-recv", "to": "mail-recv"},
    ]
    return flow_id, flow_name, _make_flow_yaml(flow_id, flow_name, nodes, edges)


def make_validate_transform_flow() -> tuple[str, str, str]:
    """HTTPS-to-HTTP with validation + transform (common pattern)."""
    flow_id = "validate-transform"
    flow_name = "HTTPS to HTTP with Validation and Transform"
    nodes = [
        _make_node("sender", "sender.http", {"path": "/api", "methods": ["POST"]}),
        _make_node(
            "validator",
            "validator.json-schema",
            {
                "schema": "resources/schemas/order.schema.json",
            },
        ),
        _make_node(
            "transform",
            "converter.json-to-xml",
            {
                "rootElement": "Order",
            },
        ),
        _make_node(
            "receiver",
            "receiver.http",
            {
                "url": "https://backend.example.com/api/orders",
                "method": "POST",
                "timeoutSeconds": 30,
            },
        ),
    ]
    edges = [
        {"from": "sender", "to": "validator"},
        {"from": "validator", "to": "transform"},
        {"from": "transform", "to": "receiver"},
    ]
    return flow_id, flow_name, _make_flow_yaml(flow_id, flow_name, nodes, edges)


def make_sftp_to_soap_flow() -> tuple[str, str, str]:
    """SFTP-to-SOAP flow: SFTP sender → SOAP receiver."""
    flow_id = "sftp-to-soap"
    flow_name = "SFTP File to SOAP Service"
    nodes = [
        _make_node(
            "sftp-sender", "sender.http", {"path": "/upload", "methods": ["POST"]}
        ),
        _make_node(
            "modifier",
            "modifier.content",
            {
                "headers": [{"name": "Content-Type", "value": "text/xml"}],
            },
        ),
        _make_node(
            "soap-recv",
            "receiver.soap",
            {
                "endpoint": "https://service.example.com/soap",
                "operation": "ProcessFile",
            },
        ),
    ]
    edges = [
        {"from": "sftp-sender", "to": "modifier"},
        {"from": "modifier", "to": "soap-recv"},
    ]
    return flow_id, flow_name, _make_flow_yaml(flow_id, flow_name, nodes, edges)


def make_odata_create_flow() -> tuple[str, str, str]:
    """OData entity creation flow: HTTP sender → OData receiver (POST)."""
    flow_id = "odata-create"
    flow_name = "OData Entity Creation"
    nodes = [
        _make_node("sender", "sender.http", {"path": "/create", "methods": ["POST"]}),
        _make_node(
            "odata-recv",
            "receiver.odata-v4",
            {
                "serviceUrl": "https://api.example.com/odata",
                "entitySet": "Customers",
                "operation": "POST",
                "timeoutSeconds": 30,
            },
        ),
    ]
    edges = [{"from": "sender", "to": "odata-recv"}]
    return flow_id, flow_name, _make_flow_yaml(flow_id, flow_name, nodes, edges)


# All synthetic artifact generators
SYNTHETIC_ARTIFACTS = [
    make_soap_calculator_flow,
    make_odata_pagination_flow,
    make_idoc_orders_flow,
    make_mail_notification_flow,
    make_soap_to_http_flow,
    make_odata_to_idoc_flow,
    make_idoc_to_mail_flow,
    make_validate_transform_flow,
    make_sftp_to_soap_flow,
    make_odata_create_flow,
]


def create_all_synthetic_artifacts(output_dir: Path | str) -> list[Path]:
    """Create all synthetic adapter artifacts in output_dir.

    Returns list of artifact directories.
    """
    output_dir = Path(output_dir)
    artifact_dirs = []

    for generator in SYNTHETIC_ARTIFACTS:
        flow_id, flow_name, flow_yaml = generator()
        artifact_dir = output_dir / f"synthetic-{flow_id}"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Write flow.yaml
        (artifact_dir / "flow.yaml").write_text(flow_yaml, encoding="utf-8")

        # Write diagram.json
        import json

        diagram = {"nodes": [], "edges": []}
        (artifact_dir / "diagram.json").write_text(
            json.dumps(diagram, indent=2) + "\n", encoding="utf-8"
        )

        # Write a test
        tests_dir = artifact_dir / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "happy-path.yaml").write_text(
            _make_test("happy-path", flow_id), encoding="utf-8"
        )

        artifact_dirs.append(artifact_dir)

    return artifact_dirs


__all__ = [
    "create_all_synthetic_artifacts",
    "SYNTHETIC_ARTIFACTS",
]
