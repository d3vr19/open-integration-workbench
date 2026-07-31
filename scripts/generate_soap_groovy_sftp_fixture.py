#!/usr/bin/env python3
"""Generate the golden fixture for `minimal/soap-groovy-sftp/`.

Spec ref: §8.5 (Golden Fixture Repository), §8.3 (import report), OW-009.

Scenario:
  Inbound SOAP envelope over HTTPS  →  Groovy extracts the payload  →
  payload written to SFTP receiver (mocked).

The fixture is synthetic. No customer artifacts.

Run from the repo root: python scripts/generate_soap_groovy_sftp_fixture.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import yaml


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "packages" / "test-fixtures" / "minimal" / "soap-groovy-sftp"


EXPECTED_FLOW = {
    "apiVersion": "oiw.dev/v1alpha1",
    "kind": "IntegrationFlow",
    "metadata": {
        "id": "soap-groovy-sftp",
        "name": "SOAP to Groovy to SFTP",
        "version": 1,
        "labels": {"archetype": "api-to-file", "sourceProtocol": "https", "targetProtocol": "sftp"},
    },
    "spec": {
        "entrypoints": [
            {
                "id": "sender-soap",
                "type": "sender.http",
                "config": {"path": "/soap", "methods": ["POST"]},
                "fidelity": "simulated",
            }
        ],
        "nodes": [
            {
                "id": "extract-payload",
                "type": "script.groovy",
                "config": {
                    # The Groovy stub interpreter supports message.setHeader/setProperty/setBody.
                    # In production this would parse the SOAP envelope and extract the body.
                    "resource": "flows/soap-groovy-sftp/resources/scripts/extractPayload.groovy",
                },
                "fidelity": "simulated",
            },
            {
                "id": "encode-base64",
                "type": "encoder.base64",
                "config": {"operation": "encode"},
                "fidelity": "compatible-subset",
            },
            {
                "id": "receiver-sftp",
                "type": "receiver.sftp",
                "config": {
                    "host": "sftp.example.invalid",
                    "port": 22,
                    "path": "/upload",
                    "fileName": "payload.b64",
                    "credentialRef": "sftp-write-client",
                },
                "fidelity": "simulated",
            },
        ],
        "edges": [
            {"from": "sender-soap", "to": "extract-payload"},
            {"from": "extract-payload", "to": "encode-base64"},
            {"from": "encode-base64", "to": "receiver-sftp"},
        ],
        "errorHandling": {
            "defaultExceptionSubprocess": {
                "steps": [
                    {
                        "id": "error-log",
                        "type": "log.message",
                        "config": {"level": "ERROR", "message": "SFTP drop failed"},
                        "fidelity": "compatible-subset",
                    }
                ]
            }
        },
        "extensions": {},
    },
}


EXTRACT_PAYLOAD_GROOVY = """// extractPayload.groovy
// Spec ref: §26.3 reference scenario variant. DEV-003: stub interpreter
// supports message.setHeader/setProperty/setBody only; full Groovy
// execution (with SOAP envelope parsing via XmlSlurper) is Phase 2.
//
// In production this would:
//   def soap = new XmlSlurper().parseText(message.getBody())
//   def payload = soap.Body.*.text()
//   message.setBody(payload)

// Stub: just forward the body unchanged and tag it.
message.setProperty("extracted", "true")
"""


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    # source.zip — native OIW fixture
    source_zip = FIXTURE_DIR / "source.zip"
    with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "flow.yaml",
            yaml.safe_dump(EXPECTED_FLOW, sort_keys=True, default_flow_style=False, allow_unicode=True),
        )
        zf.writestr("resources/scripts/extractPayload.groovy", EXTRACT_PAYLOAD_GROOVY)

    # expected-ir.yaml
    (FIXTURE_DIR / "expected-ir.yaml").write_text(
        yaml.safe_dump(EXPECTED_FLOW, sort_keys=True, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    # expected-export.zip — deterministic re-zip
    export_zip = FIXTURE_DIR / "expected-export.zip"
    with zipfile.ZipFile(export_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "flow.yaml",
            yaml.safe_dump(EXPECTED_FLOW, sort_keys=True, default_flow_style=False, allow_unicode=True),
        )
        zf.writestr("resources/scripts/extractPayload.groovy", EXTRACT_PAYLOAD_GROOVY)

    # import-report.yaml
    report = {
        "importResult": {
            "status": "FULL",
            "targetProfile": "sap-cloud-integration-2026-07",
            "recognized": [
                {"component": "oiw-flow-ir", "fidelity": "compatible-subset"},
                {"component": "https_sender", "fidelity": "simulated"},
                {"component": "groovy_script", "fidelity": "simulated"},
                {"component": "base64_encoder", "fidelity": "compatible-subset"},
                {"component": "sftp_receiver", "fidelity": "simulated"},
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
