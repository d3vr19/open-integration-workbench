#!/usr/bin/env python3
"""Generate the golden fixture for `minimal/https-content-modifier-http/`.

Spec ref: §8.5 (Golden Fixture Repository), §8.3 (import report).

This script writes:
  - source.zip               synthetic OIW-native archive containing a flow.yaml
  - expected-ir.yaml         the IR we expect the importer to produce
  - expected-export.zip      the deterministic export output
  - import-report.yaml       expected import report
  - roundtrip.diff           empty (no deviations for this fixture)

All synthetic — no customer artifacts.

Run from the repository root:
    python scripts/generate_golden_fixture.py
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import yaml


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "packages" / "test-fixtures" / "minimal" / "https-content-modifier-http"


EXPECTED_FLOW = {
    "apiVersion": "oiw.dev/v1alpha1",
    "kind": "IntegrationFlow",
    "metadata": {
        "id": "https-content-modifier-http",
        "name": "HTTPS Content Modifier to HTTP Receiver",
        "version": 1,
        "labels": {"archetype": "api-to-api"},
    },
    "spec": {
        "entrypoints": [
            {
                "id": "sender-https",
                "type": "sender.http",
                "config": {"path": "/in", "methods": ["POST"]},
                "fidelity": "simulated",
            }
        ],
        "nodes": [
            {
                "id": "modifier",
                "type": "modifier.content",
                "config": {
                    "headers": [{"name": "X-Processed-By", "value": "oiw"}],
                    "body": "{\"status\":\"ok\"}",
                },
                "fidelity": "compatible-subset",
            },
            {
                "id": "receiver-https",
                "type": "receiver.http",
                "config": {"url": "https://example.invalid/out", "method": "POST", "timeoutSeconds": 30},
                "fidelity": "simulated",
            },
        ],
        "edges": [
            {"from": "sender-https", "to": "modifier"},
            {"from": "modifier", "to": "receiver-https"},
        ],
        "extensions": {},
    },
}


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    # source.zip — native OIW fixture (flow.yaml inside the zip)
    source_zip = FIXTURE_DIR / "source.zip"
    with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "flow.yaml",
            yaml.safe_dump(EXPECTED_FLOW, sort_keys=True, default_flow_style=False, allow_unicode=True),
        )

    # expected-ir.yaml
    (FIXTURE_DIR / "expected-ir.yaml").write_text(
        yaml.safe_dump(EXPECTED_FLOW, sort_keys=True, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    # expected-export.zip — re-zip the same content deterministically
    export_zip = FIXTURE_DIR / "expected-export.zip"
    with zipfile.ZipFile(export_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "flow.yaml",
            yaml.safe_dump(EXPECTED_FLOW, sort_keys=True, default_flow_style=False, allow_unicode=True),
        )

    # import-report.yaml
    report = {
        "importResult": {
            "status": "FULL",
            "targetProfile": "sap-cloud-integration-2026-07",
            "recognized": [
                {"component": "oiw-flow-ir", "fidelity": "compatible-subset"},
                {"component": "https_sender", "fidelity": "simulated"},
                {"component": "content_modifier", "fidelity": "compatible-subset"},
                {"component": "http_receiver", "fidelity": "simulated"},
            ],
            "preservedOpaque": [],
            "unsupported": [],
            "warnings": ["native OIW archive recognized — full round-trip"],
            "digest": "sha256:<computed at runtime>",
            "sourceArchive": "source.zip",
        }
    }
    (FIXTURE_DIR / "import-report.yaml").write_text(
        yaml.safe_dump(report, sort_keys=True, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    # roundtrip.diff — no deviations for this fixture
    (FIXTURE_DIR / "roundtrip.diff").write_text(
        "# No deviations. Native OIW fixture round-trips losslessly.\n",
        encoding="utf-8",
    )

    print(f"wrote golden fixture at {FIXTURE_DIR}")


if __name__ == "__main__":
    main()
