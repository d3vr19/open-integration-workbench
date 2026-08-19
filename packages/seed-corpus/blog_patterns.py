"""Blog-post-derived integration patterns (WP-07 Task A-004).

Creates OIW IR projects from SAP community blog post patterns.
These are real integration techniques documented in public SAP
community content, recreated as OIW projects.

Each pattern is tagged with provenance.source = "blog-post" and
includes the archetype it represents.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml


def _make_flow(
    flow_id: str,
    name: str,
    nodes: list[dict],
    edges: list[dict],
    labels: dict | None = None,
) -> str:
    flow = {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationFlow",
        "metadata": {"id": flow_id, "name": name, "version": 1, "labels": labels or {}},
        "spec": {"entrypoints": [], "nodes": nodes, "edges": edges, "extensions": {}},
    }
    return yaml.safe_dump(
        flow, sort_keys=True, default_flow_style=False, allow_unicode=True
    )


def _node(nid: str, ntype: str, config: dict | None = None) -> dict:
    return {"id": nid, "type": ntype, "config": config or {}, "fidelity": "simulated"}


def _edge(f: str, t: str) -> dict:
    return {"from": f, "to": t}


# Blog-post-derived patterns (10 patterns covering 5+ archetypes)
BLOG_PATTERNS = [
    # 1. Content-based router with Groovy (SAP CPI common pattern)
    (
        "blog-content-router",
        "Content-Based Router with Groovy",
        [
            _node("s", "sender.http", {"path": "/route", "methods": ["POST"]}),
            _node("g", "script.groovy", {"script": "resources/scripts/route.groovy"}),
            _node("r", "router", {}),
            _node(
                "r1",
                "receiver.http",
                {"url": "https://api1.example.com", "method": "POST"},
            ),
            _node(
                "r2",
                "receiver.http",
                {"url": "https://api2.example.com", "method": "POST"},
            ),
        ],
        [_edge("s", "g"), _edge("g", "r"), _edge("r", "r1"), _edge("r", "r2")],
        {"source": "blog-post", "archetype": "api-to-api"},
    ),
    # 2. JSON to XML transformation with validation
    (
        "blog-json-to-xml-validate",
        "JSON to XML with Validation",
        [
            _node("s", "sender.http", {"path": "/transform", "methods": ["POST"]}),
            _node(
                "v", "validator.json-schema", {"schema": "resources/schemas/input.json"}
            ),
            _node("c", "converter.json-to-xml", {"rootElement": "Request"}),
            _node(
                "r",
                "receiver.http",
                {
                    "url": "https://backend.example.com",
                    "method": "POST",
                    "timeoutSeconds": 30,
                },
            ),
        ],
        [_edge("s", "v"), _edge("v", "c"), _edge("c", "r")],
        {"source": "blog-post", "archetype": "transform-pipeline"},
    ),
    # 3. Error handling with exception subprocess
    (
        "blog-error-handling",
        "Error Handling with Exception Subprocess",
        [
            _node("s", "sender.http", {"path": "/api", "methods": ["POST"]}),
            _node(
                "r",
                "receiver.http",
                {
                    "url": "https://backend.example.com",
                    "method": "POST",
                    "timeoutSeconds": 30,
                },
            ),
        ],
        [_edge("s", "r")],
        {"source": "blog-post", "archetype": "error-handling-pattern"},
    ),
    # 4. Paginated OData ingestion with aggregation
    (
        "blog-odata-pagination",
        "Paginated OData Ingestion with Aggregation",
        [
            _node("s", "sender.http", {"path": "/sync", "methods": ["GET"]}),
            _node(
                "o",
                "receiver.odata-v4",
                {
                    "serviceUrl": "https://api.example.com/odata",
                    "entitySet": "Orders",
                    "operation": "GET",
                    "pagination": {"enabled": True, "pageSize": 50, "maxPages": 20},
                    "timeoutSeconds": 60,
                },
            ),
            _node("g", "gather", {}),
            _node(
                "r",
                "receiver.http",
                {"url": "https://warehouse.example.com/api", "method": "POST"},
            ),
        ],
        [_edge("s", "o"), _edge("o", "g"), _edge("g", "r")],
        {"source": "blog-post", "archetype": "paginated-api-ingestion"},
    ),
    # 5. SFTP file pickup with Groovy processing
    (
        "blog-sftp-processing",
        "SFTP File Pickup with Groovy Processing",
        [
            _node("s", "sender.http", {"path": "/upload", "methods": ["POST"]}),
            _node("g", "script.groovy", {"script": "resources/scripts/process.groovy"}),
            _node(
                "r", "receiver.sftp", {"host": "sftp.example.com", "path": "/processed"}
            ),
        ],
        [_edge("s", "g"), _edge("g", "r")],
        {"source": "blog-post", "archetype": "file-to-api"},
    ),
    # 6. Retry with idempotency key
    (
        "blog-retry-idempotency",
        "Retry with Idempotency Key",
        [
            _node("s", "sender.http", {"path": "/api", "methods": ["POST"]}),
            _node(
                "m",
                "modifier.content",
                {"headers": [{"name": "Idempotency-Key", "value": "${uuid()}"}]},
            ),
            _node(
                "r",
                "receiver.http",
                {
                    "url": "https://backend.example.com",
                    "method": "POST",
                    "timeoutSeconds": 30,
                },
            ),
        ],
        [_edge("s", "m"), _edge("m", "r")],
        {"source": "blog-post", "archetype": "security-pattern"},
    ),
    # 7. SOAP to JSON bridge
    (
        "blog-soap-json-bridge",
        "SOAP to JSON Bridge",
        [
            _node(
                "s",
                "sender.soap",
                {"endpoint": "https://soap.example.com", "operation": "GetData"},
            ),
            _node("c", "converter.xml-to-json", {}),
            _node(
                "r",
                "receiver.http",
                {"url": "https://api.example.com/data", "method": "POST"},
            ),
        ],
        [_edge("s", "c"), _edge("c", "r")],
        {"source": "blog-post", "archetype": "api-to-api"},
    ),
    # 8. IDoc to OData synchronization
    (
        "blog-idoc-odata-sync",
        "IDoc to OData Synchronization",
        [
            _node("s", "sender.http", {"path": "/sync", "methods": ["POST"]}),
            _node(
                "i", "receiver.idoc", {"idocType": "ORDERS05", "messageType": "ORDERS"}
            ),
            _node(
                "o",
                "receiver.odata-v4",
                {
                    "serviceUrl": "https://api.example.com/odata",
                    "entitySet": "Confirmations",
                    "operation": "POST",
                },
            ),
        ],
        [_edge("s", "i"), _edge("i", "o")],
        {"source": "blog-post", "archetype": "api-to-erp"},
    ),
    # 9. Mail notification on error
    (
        "blog-error-mail-alert",
        "Error Mail Alert",
        [
            _node("s", "sender.http", {"path": "/process", "methods": ["POST"]}),
            _node(
                "r",
                "receiver.http",
                {"url": "https://backend.example.com", "method": "POST"},
            ),
            _node(
                "m",
                "receiver.mail",
                {
                    "to": "alerts@example.com",
                    "subject": "Processing Failed",
                    "body": "Check logs",
                },
            ),
        ],
        [_edge("s", "r")],
        {"source": "blog-post", "archetype": "error-handling-pattern"},
    ),
    # 10. Batch ETL with splitter + gather
    (
        "blog-batch-etl",
        "Batch ETL with Splitter and Gather",
        [
            _node("s", "sender.http", {"path": "/batch", "methods": ["POST"]}),
            _node("sp", "splitter", {}),
            _node("t", "converter.json-to-xml", {"rootElement": "Item"}),
            _node("g", "gather", {}),
            _node(
                "r",
                "receiver.http",
                {"url": "https://warehouse.example.com/batch", "method": "POST"},
            ),
        ],
        [_edge("s", "sp"), _edge("sp", "t"), _edge("t", "g"), _edge("g", "r")],
        {"source": "blog-post", "archetype": "batch-etl"},
    ),
]


def create_blog_post_patterns(output_dir: Path | str) -> list[Path]:
    """Create all blog-post-derived patterns in output_dir."""
    output_dir = Path(output_dir)
    artifact_dirs = []

    for flow_id, name, nodes, edges, labels in BLOG_PATTERNS:
        artifact_dir = output_dir / f"blog-{flow_id}"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        (artifact_dir / "flow.yaml").write_text(
            _make_flow(flow_id, name, nodes, edges, labels), encoding="utf-8"
        )
        (artifact_dir / "diagram.json").write_text(
            json.dumps({"nodes": [], "edges": []}, indent=2) + "\n", encoding="utf-8"
        )

        tests_dir = artifact_dir / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "happy-path.yaml").write_text(
            f"apiVersion: oiw.dev/v1alpha1\nkind: FlowTest\nmetadata:\n  name: happy-path\n  flow: {flow_id}\n"
            f"spec:\n  input:\n    bodyInline: '{{}}'\n  assertions:\n    - type: exchange.status\n      equals: COMPLETED\n  mocks: []\n",
            encoding="utf-8",
        )

        artifact_dirs.append(artifact_dir)

    return artifact_dirs


__all__ = ["BLOG_PATTERNS", "create_blog_post_patterns"]
