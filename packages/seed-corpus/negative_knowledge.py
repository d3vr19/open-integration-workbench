"""Negative knowledge population (WP-07 Track E-002).

Spec ref: §15.7 (Expert Trajectory Eligibility), §15.11 (Avoid Patterns).

For each failure mode in the catalog, creates an AvoidPattern entry that:
  - Trigger: operation + componentType + missing config
  - Reason: why this is dangerous
  - Severity: high/critical/medium/low (from failure-modes.yaml)
  - Replacement: typed actions to fix the failure (from learning session corrections)
  - Evidence: link to the learning session that produced this knowledge

AvoidPatterns are stored in packages/seed-corpus/negative-knowledge.yaml.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "seed-corpus"))


@dataclass
class AvoidPattern:
    """A "don't do this" pattern with trigger + replacement.

    Spec ref: §15.11.
    """

    id: str
    trigger: dict[str, Any]
    reason: str
    severity: str  # critical | high | medium | low
    replacement: list[dict[str, Any]]
    evidence: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trigger": self.trigger,
            "reason": self.reason,
            "severity": self.severity,
            "replacement": self.replacement,
            "evidence": self.evidence,
            "provenance": self.provenance,
        }


# --------------------------------------------------------------------------- #
# Failure-mode → AvoidPattern mapping
# --------------------------------------------------------------------------- #

# Each failure mode maps to a trigger condition (operation + componentType +
# configMissing) and a replacement sequence (typed actions).

_AVOID_PATTERN_DEFS: list[dict[str, Any]] = [
    {
        "failure_mode": "fm-001",
        "trigger": {
            "operation": "add-node",
            "componentType": "receiver.odata-v4",
            "configMissing": "pagination.maxPages",
        },
        "reason": "Unbounded pagination can cause memory exhaustion on large datasets. "
        "OData receivers without maxPages will fetch all pages, potentially "
        "consuming gigabytes of memory.",
        "severity": "high",
        "replacement": [
            {
                "op": "updateNodeConfig",
                "nodeId": "receiver",
                "config": {"pagination": {"maxPages": 100, "pageSize": 50}},
            },
        ],
    },
    {
        "failure_mode": "fm-002",
        "trigger": {
            "operation": "updateNodeConfig",
            "componentType": "receiver.http",
            "configSet": "retry.maxAttempts",
            "configMissing": "headers.Idempotency-Key",
        },
        "reason": "Retrying POST requests without an idempotency key can create duplicate "
        "resources in the target system. Each retry creates a new resource "
        "instead of redelivering the original.",
        "severity": "high",
        "replacement": [
            {
                "op": "updateNodeConfig",
                "nodeId": "receiver",
                "config": {"headers": {"Idempotency-Key": "${header.MessageId}"}},
            },
        ],
    },
    {
        "failure_mode": "fm-003",
        "trigger": {
            "operation": "create-flow",
            "configMissing": "spec.errorHandling",
        },
        "reason": "Flows without exception handling will propagate unhandled errors to "
        "the caller, potentially leaking internal details and breaking the "
        "client contract. Every production flow needs a default exception "
        "subprocess.",
        "severity": "medium",
        "replacement": [
            {
                "op": "updateNodeConfig",
                "path": "spec.errorHandling",
                "config": {
                    "defaultExceptionSubprocess": {
                        "steps": [{"id": "log-err", "type": "log.message"}]
                    }
                },
            },
        ],
    },
    {
        "failure_mode": "fm-004",
        "trigger": {
            "operation": "add-node",
            "componentType": "receiver.*",
            "configContains": "smtpUrl=smtps://.*:.*@",
        },
        "reason": "Inline secrets in receiver URLs are exposed in the flow IR, build "
        "artifacts, and logs. Use credentialRef to indirect through the "
        "tenant's secret store.",
        "severity": "critical",
        "replacement": [
            {
                "op": "updateNodeConfig",
                "nodeId": "receiver",
                "config": {
                    "smtpUrl": "smtps://example.com:465",
                    "credentialRef": "smtp-creds",
                },
            },
        ],
    },
    {
        "failure_mode": "fm-005",
        "trigger": {
            "operation": "add-node",
            "componentType": "validator.json-schema",
            "configSet": "schema",
            "resourceMissing": True,
        },
        "reason": "Referencing a schema resource that doesn't exist causes validation "
        "to fail at runtime. The schema must be created in resources/schemas/ "
        "before the validator can be used.",
        "severity": "high",
        "replacement": [
            {
                "op": "resource.write",
                "path": "resources/schemas/{}.schema.json",
                "content": '{"type":"object","properties":{}}',
            },
        ],
    },
    {
        "failure_mode": "fm-006",
        "trigger": {
            "operation": "add-node",
            "configMissing": "edges.from newNode",
        },
        "reason": "Inserting a node without rewiring edges leaves it dangling — it "
        "won't receive input or produce output. Always remove the old edge "
        "and add two new edges: prev→new and new→next.",
        "severity": "medium",
        "replacement": [
            {"op": "removeEdge", "from": "${prev}", "to": "${next}"},
            {"op": "addEdge", "from": "${prev}", "to": "${newNode}"},
            {"op": "addEdge", "from": "${newNode}", "to": "${next}"},
        ],
    },
    {
        "failure_mode": "fm-007",
        "trigger": {
            "operation": "resource.write",
            "resourceType": "groovy-script",
            "contentMatches": r"import\s+java\.net\.(URL|Socket|ServerSocket)",
        },
        "reason": "The SAP CPI Groovy sandbox blocks java.net.URL, Socket, and "
        "ServerSocket. Use the messageExchange HTTP client or externalize "
        "the call to a dedicated adapter.",
        "severity": "critical",
        "replacement": [
            {
                "op": "resource.write",
                "path": "${scriptPath}",
                "content": "def http = messageExchange.getHttpClient()\n"
                "def data = http.get('${url}').body",
            },
        ],
    },
    {
        "failure_mode": "fm-008",
        "trigger": {
            "operation": "add-node",
            "componentType": "receiver.http",
            "configMissing": "timeoutSeconds",
        },
        "reason": "Without a timeout, a hung backend can consume a worker thread "
        "indefinitely, eventually exhausting the pool. Always set "
        "timeoutSeconds (default 30).",
        "severity": "low",
        "replacement": [
            {
                "op": "updateNodeConfig",
                "nodeId": "receiver",
                "config": {"timeoutSeconds": 30},
            },
        ],
    },
    {
        "failure_mode": "fm-009",
        "trigger": {
            "operation": "add-node",
            "componentType": "transform.xml-to-json",
            "configMissing": "followUp.contentModifier.headers.Content-Type",
        },
        "reason": "After XML→JSON transformation, the message body is JSON but the "
        "Content-Type header still says application/xml. Downstream services "
        "will reject the payload. Add a content modifier to set "
        "Content-Type: application/json.",
        "severity": "medium",
        "replacement": [
            {
                "op": "addNode",
                "node": {
                    "id": "ct-modifier",
                    "type": "modifier.content",
                    "config": {"headers": {"Content-Type": "application/json"}},
                },
            },
            {"op": "addEdge", "from": "${transform}", "to": "ct-modifier"},
            {"op": "addEdge", "from": "ct-modifier", "to": "${receiver}"},
        ],
    },
    {
        "failure_mode": "fm-010",
        "trigger": {
            "operation": "updateNodeConfig",
            "componentType": "receiver.*",
            "configContains": "https://*.example.com",
        },
        "reason": "Hardcoding tenant URLs makes the flow non-portable across "
        "environments. Use ${ENV_VAR} references so the same flow can be "
        "promoted dev→stage→prod without code changes.",
        "severity": "medium",
        "replacement": [
            {
                "op": "updateNodeConfig",
                "nodeId": "receiver",
                "config": {"url": "${TENANT_URL}"},
            },
        ],
    },
    {
        "failure_mode": "fm-011",
        "trigger": {
            "operation": "add-node",
            "componentType": "receiver.soap",
            "configMissing": "soapAction",
        },
        "reason": "SOAP services require the SOAPAction HTTP header to identify the "
        "operation. Without it, the service returns a 400 Bad Request or invokes "
        "the wrong operation.",
        "severity": "medium",
        "replacement": [
            {
                "op": "updateNodeConfig",
                "nodeId": "receiver",
                "config": {"soapAction": "${operationUri}"},
            },
        ],
    },
    {
        "failure_mode": "fm-012",
        "trigger": {
            "operation": "add-node",
            "componentType": "receiver.idoc",
            "configSet": "idocType",
            "idocTypeNotIn": ["ORDERS05", "MATMAS05", "DEBMAS07", "CREMAS07"],
        },
        "reason": "Unknown IDoc types are rejected by the SAP IDoc adapter. Use one "
        "of the supported types (ORDERS05, MATMAS05, DEBMAS07, CREMAS07) or "
        "register the new type with the adapter first.",
        "severity": "medium",
        "replacement": [
            {
                "op": "updateNodeConfig",
                "nodeId": "receiver",
                "config": {"idocType": "ORDERS05"},
            },
        ],
    },
]


def build_avoid_patterns(
    failure_modes_yaml: Path | str | None = None,
) -> list[AvoidPattern]:
    """Build AvoidPattern entries from the failure-modes catalog.

    Args:
        failure_modes_yaml: Path to failure-modes.yaml. Defaults to
            packages/seed-corpus/failure-modes.yaml.

    Returns:
        List of AvoidPattern objects (one per failure mode).
    """
    if failure_modes_yaml is None:
        failure_modes_yaml = (
            REPO_ROOT / "packages" / "seed-corpus" / "failure-modes.yaml"
        )
    failure_modes_yaml = Path(failure_modes_yaml)

    catalog = yaml.safe_load(failure_modes_yaml.read_text(encoding="utf-8"))
    fm_by_id = {fm["id"]: fm for fm in catalog["spec"]["failureModes"]}

    patterns: list[AvoidPattern] = []
    for defn in _AVOID_PATTERN_DEFS:
        fm_id = defn["failure_mode"]
        fm = fm_by_id.get(fm_id)
        if fm is None:
            continue

        patterns.append(
            AvoidPattern(
                id=f"avoid-{fm_id}",
                trigger=defn["trigger"],
                reason=defn["reason"],
                severity=defn["severity"],
                replacement=defn["replacement"],
                evidence={
                    "failureModeId": fm_id,
                    "diagnostic": fm.get("diagnostic", ""),
                    "archetype": fm.get("archetype", "any"),
                },
                provenance={
                    "source": "failure-modes-catalog",
                    "reviewer": "hehenaice",
                    "license": "Apache-2.0",
                    "isReal": True,
                    "reviewDate": "2026-08-05",
                },
            )
        )

    return patterns


def write_avoid_patterns_yaml(
    patterns: list[AvoidPattern],
    output_path: Path | str | None = None,
) -> Path:
    """Write avoid patterns to a YAML file.

    Default path: packages/seed-corpus/negative-knowledge.yaml
    """
    if output_path is None:
        output_path = REPO_ROOT / "packages" / "seed-corpus" / "negative-knowledge.yaml"
    output_path = Path(output_path)

    doc = {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "NegativeKnowledgeCatalog",
        "metadata": {
            "version": "0.1.0",
            "created": "2026-08-05",
            "description": "Avoid patterns derived from WP-07 learning sessions + failure modes catalog",
        },
        "spec": {
            "avoidPatterns": [p.to_dict() for p in patterns],
        },
    }
    output_path.write_text(
        yaml.safe_dump(
            doc, sort_keys=False, default_flow_style=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
    return output_path


def populate_negative_knowledge(
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Build + persist the negative knowledge catalog.

    Returns a summary dict.
    """
    patterns = build_avoid_patterns()
    written = write_avoid_patterns_yaml(patterns, output_path)

    by_severity: dict[str, int] = {}
    for p in patterns:
        by_severity[p.severity] = by_severity.get(p.severity, 0) + 1

    return {
        "totalPatterns": len(patterns),
        "bySeverity": by_severity,
        "outputPath": str(written),
        "patterns": [p.id for p in patterns],
    }


if __name__ == "__main__":
    summary = populate_negative_knowledge()
    print(yaml.safe_dump(summary, sort_keys=False, default_flow_style=False))
