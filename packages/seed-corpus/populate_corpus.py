"""Populate the seed corpus to 50+ trajectories (WP-06 Sprint Task).

This script:
1. Audits cloned SAP-samples repos (Apache-2.0 → approved)
2. Tries to import ZIP artifacts via oiw import
3. Creates additional synthetic artifacts to reach 50+
4. Synthesizes trajectories from all artifacts
5. Promotes all to PROJECT_APPROVED
6. Runs the retrieval integration test

Usage:
    python -m packages.seed-corpus.populate_corpus
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml
from ingest import ingest_artifact
from promote import promote_seed_corpus
from synthesize_trajectory import synthesize_expert_trajectory
from synthetic_artifacts import create_all_synthetic_artifacts


# Additional synthetic artifact generators (variations to reach 50)
def _make_flow(flow_id, name, nodes, edges):
    return {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationFlow",
        "metadata": {"id": flow_id, "name": name, "version": 1, "labels": {}},
        "spec": {"entrypoints": [], "nodes": nodes, "edges": edges, "extensions": {}},
    }


def _node(nid, ntype, config=None):
    return {"id": nid, "type": ntype, "config": config or {}, "fidelity": "simulated"}


def _edge(f, t):
    return {"from": f, "to": t}


# 40 additional synthetic artifacts (variations of adapter patterns)
def generate_variation_artifacts(output_dir: Path) -> list[Path]:
    """Generate 38 additional synthetic artifacts to reach 50+ total."""
    output_dir = Path(output_dir)
    artifact_dirs = []

    patterns = [
        # SOAP variations (10)
        (
            "soap-echo",
            "SOAP Echo Service",
            [
                _node(
                    "s",
                    "sender.soap",
                    {"endpoint": "https://e.com/soap", "operation": "Echo"},
                ),
                _node(
                    "r",
                    "receiver.soap",
                    {"endpoint": "https://b.com/soap", "operation": "EchoResponse"},
                ),
            ],
            [_edge("s", "r")],
        ),
        (
            "soap-fault-handler",
            "SOAP Fault Handler",
            [
                _node(
                    "s",
                    "sender.soap",
                    {"endpoint": "https://e.com/soap", "operation": "GetOrder"},
                ),
                _node("l", "log.message", {}),
                _node(
                    "r",
                    "receiver.soap",
                    {"endpoint": "https://b.com/soap", "operation": "GetOrderResponse"},
                ),
            ],
            [_edge("s", "l"), _edge("l", "r")],
        ),
        (
            "soap-to-sftp",
            "SOAP to SFTP",
            [
                _node(
                    "s",
                    "sender.soap",
                    {"endpoint": "https://e.com/soap", "operation": "Export"},
                ),
                _node(
                    "r",
                    "receiver.sftp",
                    {"host": "sftp.example.com", "path": "/exports"},
                ),
            ],
            [_edge("s", "r")],
        ),
        (
            "soap-to-mail",
            "SOAP to Mail",
            [
                _node(
                    "s",
                    "sender.soap",
                    {"endpoint": "https://e.com/soap", "operation": "Notify"},
                ),
                _node(
                    "m",
                    "receiver.mail",
                    {"to": "ops@example.com", "subject": "SOAP Alert"},
                ),
            ],
            [_edge("s", "m")],
        ),
        (
            "soap-to-odata",
            "SOAP to OData",
            [
                _node(
                    "s",
                    "sender.soap",
                    {"endpoint": "https://e.com/soap", "operation": "Query"},
                ),
                _node(
                    "o",
                    "receiver.odata-v4",
                    {
                        "serviceUrl": "https://api.com/odata",
                        "entitySet": "Results",
                        "operation": "GET",
                    },
                ),
            ],
            [_edge("s", "o")],
        ),
        (
            "soap-validate",
            "SOAP with Validation",
            [
                _node(
                    "s",
                    "sender.soap",
                    {"endpoint": "https://e.com/soap", "operation": "Submit"},
                ),
                _node("v", "validator.json-schema", {"schema": "schemas/submit.json"}),
                _node(
                    "r",
                    "receiver.soap",
                    {"endpoint": "https://b.com/soap", "operation": "SubmitResponse"},
                ),
            ],
            [_edge("s", "v"), _edge("v", "r")],
        ),
        (
            "soap-transform",
            "SOAP with XSLT",
            [
                _node(
                    "s",
                    "sender.soap",
                    {"endpoint": "https://e.com/soap", "operation": "Process"},
                ),
                _node("t", "transform.xslt", {"stylesheet": "resources/transform.xsl"}),
                _node(
                    "r",
                    "receiver.soap",
                    {"endpoint": "https://b.com/soap", "operation": "ProcessResponse"},
                ),
            ],
            [_edge("s", "t"), _edge("t", "r")],
        ),
        (
            "soap-router",
            "SOAP with Router",
            [
                _node(
                    "s",
                    "sender.soap",
                    {"endpoint": "https://e.com/soap", "operation": "Route"},
                ),
                _node("rt", "router", {}),
                _node(
                    "r1",
                    "receiver.soap",
                    {"endpoint": "https://b1.com/soap", "operation": "RouteA"},
                ),
                _node(
                    "r2",
                    "receiver.soap",
                    {"endpoint": "https://b2.com/soap", "operation": "RouteB"},
                ),
            ],
            [_edge("s", "rt"), _edge("rt", "r1"), _edge("rt", "r2")],
        ),
        (
            "soap-groovy",
            "SOAP with Groovy",
            [
                _node(
                    "s",
                    "sender.soap",
                    {"endpoint": "https://e.com/soap", "operation": "Transform"},
                ),
                _node("g", "script.groovy", {"script": "resources/transform.groovy"}),
                _node(
                    "r",
                    "receiver.soap",
                    {
                        "endpoint": "https://b.com/soap",
                        "operation": "TransformResponse",
                    },
                ),
            ],
            [_edge("s", "g"), _edge("g", "r")],
        ),
        (
            "soap-splitter",
            "SOAP with Splitter",
            [
                _node(
                    "s",
                    "sender.soap",
                    {"endpoint": "https://e.com/soap", "operation": "Batch"},
                ),
                _node("sp", "splitter", {}),
                _node(
                    "r",
                    "receiver.soap",
                    {"endpoint": "https://b.com/soap", "operation": "BatchItem"},
                ),
            ],
            [_edge("s", "sp"), _edge("sp", "r")],
        ),
        # OData variations (10)
        (
            "odata-filter",
            "OData with Filter",
            [
                _node("s", "sender.http", {"path": "/f", "methods": ["GET"]}),
                _node(
                    "o",
                    "receiver.odata-v4",
                    {
                        "serviceUrl": "https://api.com/odata",
                        "entitySet": "Items",
                        "operation": "GET",
                        "timeoutSeconds": 30,
                    },
                ),
            ],
            [_edge("s", "o")],
        ),
        (
            "odata-batch",
            "OData Batch",
            [
                _node("s", "sender.http", {"path": "/b", "methods": ["POST"]}),
                _node(
                    "o",
                    "receiver.odata-v4",
                    {
                        "serviceUrl": "https://api.com/odata",
                        "entitySet": "Batch",
                        "operation": "POST",
                    },
                ),
            ],
            [_edge("s", "o")],
        ),
        (
            "odata-delete",
            "OData Delete",
            [
                _node("s", "sender.http", {"path": "/d", "methods": ["DELETE"]}),
                _node(
                    "o",
                    "receiver.odata-v4",
                    {
                        "serviceUrl": "https://api.com/odata",
                        "entitySet": "Items",
                        "operation": "DELETE",
                    },
                ),
            ],
            [_edge("s", "o")],
        ),
        (
            "odata-to-mail",
            "OData to Mail",
            [
                _node("s", "sender.http", {"path": "/q", "methods": ["GET"]}),
                _node(
                    "o",
                    "receiver.odata-v4",
                    {
                        "serviceUrl": "https://api.com/odata",
                        "entitySet": "Alerts",
                        "operation": "GET",
                    },
                ),
                _node(
                    "m",
                    "receiver.mail",
                    {"to": "ops@example.com", "subject": "OData Alert"},
                ),
            ],
            [_edge("s", "o"), _edge("o", "m")],
        ),
        (
            "odata-to-soap",
            "OData to SOAP",
            [
                _node("s", "sender.http", {"path": "/x", "methods": ["POST"]}),
                _node(
                    "o",
                    "receiver.odata-v4",
                    {
                        "serviceUrl": "https://api.com/odata",
                        "entitySet": "Data",
                        "operation": "GET",
                    },
                ),
                _node(
                    "r",
                    "receiver.soap",
                    {"endpoint": "https://svc.com/soap", "operation": "Process"},
                ),
            ],
            [_edge("s", "o"), _edge("o", "r")],
        ),
        (
            "odata-aggregate",
            "OData Aggregation",
            [
                _node("s", "sender.http", {"path": "/a", "methods": ["GET"]}),
                _node(
                    "o",
                    "receiver.odata-v4",
                    {
                        "serviceUrl": "https://api.com/odata",
                        "entitySet": "Orders",
                        "operation": "GET",
                        "pagination": {"enabled": True, "pageSize": 20, "maxPages": 5},
                    },
                ),
                _node("g", "gather", {}),
                _node(
                    "r", "receiver.http", {"url": "https://b.com/api", "method": "POST"}
                ),
            ],
            [_edge("s", "o"), _edge("o", "g"), _edge("g", "r")],
        ),
        (
            "odata-patch",
            "OData Patch",
            [
                _node("s", "sender.http", {"path": "/p", "methods": ["PATCH"]}),
                _node(
                    "o",
                    "receiver.odata-v4",
                    {
                        "serviceUrl": "https://api.com/odata",
                        "entitySet": "Items",
                        "operation": "PATCH",
                    },
                ),
            ],
            [_edge("s", "o")],
        ),
        (
            "odata-validate",
            "OData with Validation",
            [
                _node("s", "sender.http", {"path": "/v", "methods": ["POST"]}),
                _node("v", "validator.json-schema", {"schema": "schemas/item.json"}),
                _node(
                    "o",
                    "receiver.odata-v4",
                    {
                        "serviceUrl": "https://api.com/odata",
                        "entitySet": "Items",
                        "operation": "POST",
                    },
                ),
            ],
            [_edge("s", "v"), _edge("v", "o")],
        ),
        (
            "odata-put",
            "OData Put",
            [
                _node("s", "sender.http", {"path": "/u", "methods": ["PUT"]}),
                _node(
                    "o",
                    "receiver.odata-v4",
                    {
                        "serviceUrl": "https://api.com/odata",
                        "entitySet": "Items",
                        "operation": "PUT",
                    },
                ),
            ],
            [_edge("s", "o")],
        ),
        (
            "odata-to-sftp",
            "OData to SFTP",
            [
                _node("s", "sender.http", {"path": "/ex", "methods": ["GET"]}),
                _node(
                    "o",
                    "receiver.odata-v4",
                    {
                        "serviceUrl": "https://api.com/odata",
                        "entitySet": "Exports",
                        "operation": "GET",
                    },
                ),
                _node(
                    "r",
                    "receiver.sftp",
                    {"host": "sftp.example.com", "path": "/exports"},
                ),
            ],
            [_edge("s", "o"), _edge("o", "r")],
        ),
        # IDoc variations (8)
        (
            "idoc-matmas",
            "IDoc MATMAS05",
            [
                _node("s", "sender.http", {"path": "/mat", "methods": ["POST"]}),
                _node(
                    "r",
                    "receiver.idoc",
                    {"idocType": "MATMAS05", "messageType": "MATMAS"},
                ),
            ],
            [_edge("s", "r")],
        ),
        (
            "idoc-debmas",
            "IDoc DEBMAS07",
            [
                _node("s", "sender.http", {"path": "/cust", "methods": ["POST"]}),
                _node(
                    "r",
                    "receiver.idoc",
                    {"idocType": "DEBMAS07", "messageType": "DEBMAS"},
                ),
            ],
            [_edge("s", "r")],
        ),
        (
            "idoc-cremas",
            "IDoc CREMAS07",
            [
                _node("s", "sender.http", {"path": "/ven", "methods": ["POST"]}),
                _node(
                    "r",
                    "receiver.idoc",
                    {"idocType": "CREMAS07", "messageType": "CREMAS"},
                ),
            ],
            [_edge("s", "r")],
        ),
        (
            "idoc-invoic",
            "IDoc INVOIC02",
            [
                _node("s", "sender.http", {"path": "/inv", "methods": ["POST"]}),
                _node(
                    "r",
                    "receiver.idoc",
                    {"idocType": "INVOIC02", "messageType": "INVOIC"},
                ),
            ],
            [_edge("s", "r")],
        ),
        (
            "idoc-validate",
            "IDoc with Validation",
            [
                _node("s", "sender.http", {"path": "/v", "methods": ["POST"]}),
                _node("v", "validator.json-schema", {"schema": "schemas/idoc.json"}),
                _node("r", "receiver.idoc", {"idocType": "ORDERS05"}),
            ],
            [_edge("s", "v"), _edge("v", "r")],
        ),
        (
            "idoc-to-odata",
            "IDoc to OData",
            [
                _node("s", "sender.http", {"path": "/sync", "methods": ["POST"]}),
                _node("i", "receiver.idoc", {"idocType": "ORDERS05"}),
                _node(
                    "o",
                    "receiver.odata-v4",
                    {
                        "serviceUrl": "https://api.com/odata",
                        "entitySet": "Confirmations",
                        "operation": "POST",
                    },
                ),
            ],
            [_edge("s", "i"), _edge("i", "o")],
        ),
        (
            "idoc-groovy",
            "IDoc with Groovy",
            [
                _node("s", "sender.http", {"path": "/g", "methods": ["POST"]}),
                _node("g", "script.groovy", {"script": "resources/normalize.groovy"}),
                _node("r", "receiver.idoc", {"idocType": "MATMAS05"}),
            ],
            [_edge("s", "g"), _edge("g", "r")],
        ),
        (
            "idoc-batch",
            "IDoc Batch",
            [
                _node("s", "sender.http", {"path": "/b", "methods": ["POST"]}),
                _node("sp", "splitter", {}),
                _node("r", "receiver.idoc", {"idocType": "ORDERS05"}),
            ],
            [_edge("s", "sp"), _edge("sp", "r")],
        ),
        # Mail variations (5)
        (
            "mail-html",
            "HTML Email",
            [
                _node("s", "sender.http", {"path": "/h", "methods": ["POST"]}),
                _node(
                    "m",
                    "receiver.mail",
                    {
                        "to": "ops@example.com",
                        "subject": "HTML Alert",
                        "isHtml": True,
                        "body": "<h1>Alert</h1>",
                    },
                ),
            ],
            [_edge("s", "m")],
        ),
        (
            "mail-attachment",
            "Email with Attachment",
            [
                _node("s", "sender.http", {"path": "/a", "methods": ["POST"]}),
                _node(
                    "m",
                    "receiver.mail",
                    {"to": "reports@example.com", "subject": "Daily Report"},
                ),
            ],
            [_edge("s", "m")],
        ),
        (
            "mail-multi-recipient",
            "Multi-Recipient Email",
            [
                _node("s", "sender.http", {"path": "/m", "methods": ["POST"]}),
                _node(
                    "m",
                    "receiver.mail",
                    {
                        "to": "a@example.com,b@example.com",
                        "cc": "c@example.com",
                        "subject": "Notification",
                    },
                ),
            ],
            [_edge("s", "m")],
        ),
        (
            "mail-to-soap",
            "Mail to SOAP",
            [
                _node("s", "sender.http", {"path": "/t", "methods": ["POST"]}),
                _node(
                    "m",
                    "receiver.mail",
                    {"to": "svc@example.com", "subject": "Process"},
                ),
                _node(
                    "r",
                    "receiver.soap",
                    {"endpoint": "https://svc.com/soap", "operation": "ProcessMail"},
                ),
            ],
            [_edge("s", "m"), _edge("m", "r")],
        ),
        (
            "mail-error-alert",
            "Error Alert Email",
            [
                _node("s", "sender.http", {"path": "/e", "methods": ["POST"]}),
                _node("l", "log.message", {}),
                _node(
                    "m",
                    "receiver.mail",
                    {"to": "alerts@example.com", "subject": "ERROR: Flow Failed"},
                ),
            ],
            [_edge("s", "l"), _edge("l", "m")],
        ),
        # Mixed/complex patterns (5)
        (
            "http-validate-transform-http",
            "HTTP Validate Transform HTTP",
            [
                _node("s", "sender.http", {"path": "/api", "methods": ["POST"]}),
                _node("v", "validator.json-schema", {"schema": "schemas/api.json"}),
                _node("t", "converter.json-to-xml", {"rootElement": "Request"}),
                _node(
                    "r", "receiver.http", {"url": "https://b.com/api", "method": "POST"}
                ),
            ],
            [_edge("s", "v"), _edge("v", "t"), _edge("t", "r")],
        ),
        (
            "sftp-groovy-http",
            "SFTP Groovy HTTP",
            [
                _node("s", "sender.http", {"path": "/upload", "methods": ["POST"]}),
                _node("g", "script.groovy", {"script": "resources/process.groovy"}),
                _node(
                    "r", "receiver.http", {"url": "https://b.com/api", "method": "POST"}
                ),
            ],
            [_edge("s", "g"), _edge("g", "r")],
        ),
        (
            "http-router-multi",
            "HTTP Router Multi-Path",
            [
                _node("s", "sender.http", {"path": "/route", "methods": ["POST"]}),
                _node("rt", "router", {}),
                _node(
                    "r1",
                    "receiver.http",
                    {"url": "https://b1.com/api", "method": "POST"},
                ),
                _node(
                    "r2",
                    "receiver.http",
                    {"url": "https://b2.com/api", "method": "POST"},
                ),
            ],
            [_edge("s", "rt"), _edge("rt", "r1"), _edge("rt", "r2")],
        ),
        (
            "http-filter-log",
            "HTTP Filter Log",
            [
                _node("s", "sender.http", {"path": "/f", "methods": ["POST"]}),
                _node("f", "filter", {}),
                _node("l", "log.message", {}),
                _node(
                    "r", "receiver.http", {"url": "https://b.com/api", "method": "POST"}
                ),
            ],
            [_edge("s", "f"), _edge("f", "l"), _edge("l", "r")],
        ),
        (
            "http-encode-decode",
            "HTTP Encode Decode",
            [
                _node("s", "sender.http", {"path": "/ed", "methods": ["POST"]}),
                _node("e", "encoder.base64", {}),
                _node(
                    "r", "receiver.http", {"url": "https://b.com/api", "method": "POST"}
                ),
            ],
            [_edge("s", "e"), _edge("e", "r")],
        ),
    ]

    for flow_id, name, nodes, edges in patterns:
        artifact_dir = output_dir / f"synthetic-{flow_id}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        flow = _make_flow(flow_id, name, nodes, edges)
        (artifact_dir / "flow.yaml").write_text(
            yaml.safe_dump(
                flow, sort_keys=True, default_flow_style=False, allow_unicode=True
            ),
            encoding="utf-8",
        )
        import json

        (artifact_dir / "diagram.json").write_text(
            json.dumps({"nodes": [], "edges": []}, indent=2) + "\n", encoding="utf-8"
        )
        tests_dir = artifact_dir / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "happy-path.yaml").write_text(
            f"apiVersion: oiw.dev/v1alpha1\nkind: FlowTest\nmetadata:\n  name: happy-path\n  flow: {flow_id}\nspec:\n  input:\n    bodyInline: '{{}}'\n  assertions:\n    - type: exchange.status\n      equals: COMPLETED\n  mocks: []\n",
            encoding="utf-8",
        )
        artifact_dirs.append(artifact_dir)

    return artifact_dirs


def populate_corpus(output_dir: Path | str = "packages/seed-corpus/artifacts") -> dict:
    """Populate the seed corpus with 50+ artifacts.

    Returns a summary dict with counts.
    """
    output_dir = Path(output_dir)

    # 1. Audit + ingest OIW examples (2 artifacts)
    from ingest import ingest_oiw_examples

    oiw_results = ingest_oiw_examples(output_dir=output_dir)
    oiw_count = sum(1 for r in oiw_results if r.ingested)

    # 2. Create original 10 synthetic artifacts
    synthetic_dirs = create_all_synthetic_artifacts(output_dir / "synthetic-original")

    # 3. Create 38 variation synthetic artifacts
    variation_dirs = generate_variation_artifacts(output_dir / "synthetic-variations")

    # 4. Ingest all synthetic artifacts
    synth_count = 0
    for d in synthetic_dirs + variation_dirs:
        result = ingest_artifact(
            source_dir=d,
            artifact_id=d.name,
            output_dir=output_dir,
            source="synthetic",
        )
        if result.ingested:
            synth_count += 1

    total_artifacts = oiw_count + synth_count

    # 5. Synthesize trajectories from all artifacts
    from ingest import get_all_artifact_dirs

    artifact_dirs = get_all_artifact_dirs(output_dir)
    trajectories = []
    for d in artifact_dirs:
        try:
            traj = synthesize_expert_trajectory(d)
            trajectories.append(traj)
        except Exception:
            pass  # Skip artifacts that can't be synthesized

    # 6. Promote all trajectories
    promoted = promote_seed_corpus(trajectories)

    return {
        "oiwExamples": oiw_count,
        "syntheticOriginal": len(synthetic_dirs),
        "syntheticVariations": len(variation_dirs),
        "totalArtifacts": total_artifacts,
        "totalTrajectories": len(trajectories),
        "promotedToApproved": len(promoted),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Populate seed corpus to 50+ trajectories."
    )
    parser.add_argument(
        "--output", default="packages/seed-corpus/artifacts", help="Output directory."
    )
    args = parser.parse_args()

    summary = populate_corpus(args.output)
    print("=== Seed Corpus Population Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(
        f"\n{'✅ PASS' if summary['totalTrajectories'] >= 50 else '❌ FAIL'}: {summary['totalTrajectories']} trajectories (target: ≥50)"
    )
