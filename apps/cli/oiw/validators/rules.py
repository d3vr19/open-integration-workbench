"""Rule-based validators with stable codes.

Spec ref: §14.1 (rule table), §14.2 (OPA/Rego), §14.3 (Semgrep).
This module implements the rule codes from §14.1 in pure Python.
The Rego and Semgrep rules live in packages/policy-rules/ and run in CI.
"""

from __future__ import annotations

import re
from typing import Any

from ..project import FlowNode, IntegrationFlow, Project

# Forbidden Groovy patterns (spec §9.6 blocked list, §14.1 OIW-E004)
_FORBIDDEN_GROOVY = [
    ("Runtime.getRuntime", "java.lang.Runtime"),
    ("ProcessBuilder", "java.lang.ProcessBuilder"),
    ("System.exit", "java.lang.System.exit"),
    ("GroovyShell", "groovy.lang.GroovyShell"),
    ("GroovyClassLoader", "groovy.lang.GroovyClassLoader"),
    ("ScriptEngine", "javax.script.ScriptEngine"),
    ("java.net.Socket", "java.net.Socket"),
    ("java.net.URL", "java.net.URL"),
    ("HttpURLConnection", "java.net.HttpURLConnection"),
    ("FileWriter", "java.io.FileWriter"),
    ("FileOutputStream", "java.io.FileOutputStream"),
    ("java.lang.reflect", "java.lang.reflect"),
    ("java.lang.Thread", "java.lang.Thread"),
]

# Patterns that look like inline secrets (spec §14.1 OIW-E002)
# Matches both YAML-style (`password: "value"`) and JSON-style (`"password": "value"`).
_SECRET_PATTERNS = [
    re.compile(r"""(?i)["']?(password|passwd|secret|api[_-]?key|token)["']?\s*[:=]\s*["'][^"']{6,}["']"""),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9_\-\.]{20,}"),
    re.compile(r"-----BEGIN\s+(RSA\s+|EC\s+|OPENSSH\s+|)PRIVATE\s+KEY-----"),
]


def run_rule_validators(project: Project) -> tuple[list[str], list[str]]:
    """Apply all §14.1 rules. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    for flow in project.flows:
        flow_err, flow_warn = _validate_flow(project, flow)
        errors.extend(flow_err)
        warnings.extend(flow_warn)

    return errors, warnings


def _validate_flow(project: Project, flow: IntegrationFlow) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for node in flow.nodes:
        messages = _check_node(project, flow, node)
        for msg in messages:
            if msg.startswith("OIW-W"):
                warnings.append(msg)
            else:
                errors.append(msg)

    # Error handling presence (OIW-W002)
    if flow.error_handling is None or not flow.error_handling.steps:
        warnings.append(f"OIW-W002: flow '{flow.id}' has no error-handling subprocess")

    return errors, warnings


def _check_node(project: Project, flow: IntegrationFlow, node: FlowNode) -> list[str]:
    """Return a list of errors AND warnings for a single node.

    The list contains both ERRORs (prefixed OIW-E0xx) and WARNINGs (prefixed
    OIW-W0xx). The caller filters by prefix when --strict is set.
    """
    errors: list[str] = []

    # OIW-E001: missing endpoint configuration
    if node.type in ("receiver.http", "sender.http") and not node.config:
        errors.append(f"OIW-E001: {node.type} node '{node.id}' in flow '{flow.id}' has no config")

    # OIW-E002: inline secrets in node config
    config_str = _stringify(node.config)
    for pattern in _SECRET_PATTERNS:
        if pattern.search(config_str):
            errors.append(
                f"OIW-E002: inline secret detected in node '{node.id}' config (flow '{flow.id}'); use credentialRef"
            )

    # OIW-E002: credentialRef must not contain the actual secret value
    cred_ref = node.config.get("credentialRef")
    if isinstance(cred_ref, str) and len(cred_ref) > 200:
        errors.append(
            f"OIW-E002: credentialRef on node '{node.id}' (flow '{flow.id}') looks like an inline secret (length {len(cred_ref)}); use an identifier"
        )

    # OIW-E003: unbounded splitter
    if (
        node.type == "splitter.general"
        and not node.config.get("maxIterations")
        and not node.config.get("maxItems")
    ):
        errors.append(
            f"OIW-E003: splitter node '{node.id}' in flow '{flow.id}' has no maxIterations/maxItems (unbounded)"
        )

    # OIW-E004: forbidden Groovy constructs
    if node.type == "script.groovy":
        resource_path = node.config.get("resource")
        if resource_path:
            content = project.get_resource(resource_path)
            if content is not None:
                text = content.decode("utf-8", errors="replace")
                for marker, fqcn in _FORBIDDEN_GROOVY:
                    if marker in text:
                        errors.append(
                            f"OIW-E004: script '{resource_path}' (node '{node.id}', flow '{flow.id}') contains forbidden {fqcn}"
                        )

    # OIW-E005: insecure TLS
    if node.type in ("receiver.http", "sender.http"):
        url = node.config.get("url") or node.config.get("path", "")
        if isinstance(url, str) and url.startswith("http://"):
            errors.append(
                f"OIW-E005: {node.type} node '{node.id}' in flow '{flow.id}' must use HTTPS (found http://)"
            )

    # OIW-E006: credentials to non-allowlisted host (we allow https only; warn for any non-localhost in dev)
    if node.type == "receiver.http" and node.config.get("credentialRef"):
        url = node.config.get("url", "")
        if isinstance(url, str) and url.startswith("https://") and not _is_safe_placeholder_host(url):
            # In dev we warn; production policy would deny.
            errors.append(
                f"OIW-W005: receiver '{node.id}' (flow '{flow.id}') sends credential to non-localhost host: {url[:60]}"
            )

    # OIW-W001: missing timeout on receiver
    if node.type == "receiver.http" and not node.config.get("timeoutSeconds"):
        errors.append(f"OIW-W001: receiver '{node.id}' in flow '{flow.id}' has no timeoutSeconds")

    # OIW-W006: unvalidated inbound payload
    if node.type == "sender.http":
        # Look for a downstream validator.json-schema node
        downstream_validators = _find_downstream_validators(flow, node.id)
        if not downstream_validators:
            errors.append(
                f"OIW-W006: sender '{node.id}' in flow '{flow.id}' has no downstream JSON Schema validator"
            )

    # OIW-W007: large message retained in memory (heuristic: no splitter/gather bound)
    if node.type in ("gather",) and not node.config.get("maxItems"):
        errors.append(
            f"OIW-W007: gather node '{node.id}' in flow '{flow.id}' has no maxItems (excessively large message retained in memory)"
        )

    # OIW-W009: deprecated component (none currently; reserved)
    # OIW-W010: ambiguous content-type conversion
    if node.type in ("converter.json-to-xml", "converter.xml-to-json") and not node.config.get("rootElement"):
        errors.append(
            f"OIW-W010: converter node '{node.id}' in flow '{flow.id}' has no rootElement specified (ambiguous conversion)"
        )

    # OIW-W012: POST retry without idempotency key
    if node.type == "receiver.http":
        method = (node.config.get("method") or "POST").upper()
        retry_enabled = (
            node.config.get("retry", {}).get("enabled")
            if isinstance(node.config.get("retry"), dict)
            else node.config.get("retryEnabled")
        )
        idem_key = node.config.get("idempotencyKey") or node.config.get("idempotencyKeyHeader")
        if method == "POST" and retry_enabled and not idem_key:
            errors.append(
                f"OIW-W012: receiver '{node.id}' in flow '{flow.id}' retries POST without idempotency key"
            )

    return errors


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        import json

        return json.dumps(value, sort_keys=True)
    except Exception:
        return str(value)


def _find_downstream_validators(flow: IntegrationFlow, start_node_id: str) -> list[str]:
    """BFS from start_node_id; return any validator.json-schema node IDs reachable."""
    adjacency: dict[str, list[str]] = {}
    for edge in flow.edges:
        adjacency.setdefault(edge.from_, []).append(edge.to)
    visited: set[str] = set()
    queue = [start_node_id]
    found: list[str] = []
    while queue:
        node_id = queue.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        for nxt in adjacency.get(node_id, []):
            for n in flow.nodes:
                if n.id == nxt and n.type == "validator.json-schema":
                    found.append(n.id)
            queue.append(nxt)
    return found


# RFC 2606 / RFC 6761 reserved documentation TLDs — guaranteed never to route.
# We do NOT warn OIW-W005 for these (they cannot leak credentials anywhere real).
_SAFE_PLACEHOLDER_TLDS = (
    ".example",
    ".example.com",
    ".example.net",
    ".example.org",
    ".invalid",
    ".localhost",
    ".test",
    ".local",
)


def _is_safe_placeholder_host(url: str) -> bool:
    """Return True for localhost, loopback, or RFC-2606 reserved documentation hosts."""
    lowered = url.lower()
    if "://localhost" in lowered or "://127.0.0.1" in lowered or "://[::1]" in lowered:
        return True
    # Extract host portion
    try:
        after_scheme = lowered.split("://", 1)[1]
        host = after_scheme.split("/", 1)[0].split("?", 1)[0].split(":", 1)[0]
    except IndexError:
        return False
    return any(host.endswith(tld) for tld in _SAFE_PLACEHOLDER_TLDS)
