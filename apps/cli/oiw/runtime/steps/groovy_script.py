"""Groovy script step (sandboxed stub).

Spec ref: §9.4 (`script.groovy`, fidelity=simulated), §9.6 (Groovy Sandbox),
§16.1 threat 2 (hostile Groovy script -> RCE).

**CRITICAL LIMITATION (DEV-003)**: The current Python prototype does NOT
execute Groovy. It runs a constrained Python-based DSL that emulates the
commonly-used Groovy primitives (header/property manipulation, JSON slurp,
XML parse). This is a **stub** — real Groovy scripts will NOT produce correct
output. Full Groovy execution with process isolation, seccomp, and network
namespace isolation is Phase 2 work (OW-003 / services/runtime-worker).

**Do not rely on Groovy step results for correctness validation.** A flow
that depends on Groovy script output (e.g., dynamic header values set by
the script) will see the stub's default behavior, not the real Groovy output.

The script content is statically scanned against the §9.6 blocked list
before any execution attempt. Forbidden constructs cause an exception.
"""

from __future__ import annotations

import re
from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register

# §9.6 blocked list (compile-time + runtime)
_BLOCKED = [
    "Runtime.getRuntime",
    "ProcessBuilder",
    "System.exit",
    "GroovyShell",
    "GroovyClassLoader",
    "ScriptEngine",
    "java.net.Socket",
    "java.net.URL",
    "HttpURLConnection",
    "FileWriter",
    "FileOutputStream",
    "java.lang.reflect",
    "java.lang.Thread",
]


class GroovyScript(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "script.groovy",
            "name": "Groovy Script (sandboxed stub)",
            "description": (
                "Runs a constrained subset of Groovy-like primitives. "
                "DEV-003: full Groovy execution deferred to Phase 2 (services/runtime-worker)."
            ),
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "resource": {
                    "type": "string",
                    "description": "Path to .groovy file under resources/scripts/.",
                },
                "script": {"type": "string", "description": "Inline script (discouraged; prefer resource)."},
            },
            "oneOf": [{"required": ["resource"]}, {"required": ["script"]}],
        }

    def validate(self, node: FlowNode) -> list[str]:
        errors: list[str] = []
        if not node.config.get("resource") and not node.config.get("script"):
            errors.append(f"OIW-E001: groovy node '{node.id}' must specify either 'resource' or 'script'")
        return errors

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(node.id, "enter", "executing groovy script (stub)")
        script_text = self._load_script(node, ctx)
        # Static sandbox check
        for blocked in _BLOCKED:
            if blocked in script_text:
                ctx.exchange_status = "FAILED"
                ctx.exception = RuntimeError(f"OIW-E004: forbidden construct '{blocked}' in groovy script")
                ctx.add_trace(node.id, "error", f"forbidden: {blocked}")
                return ctx

        # Execute the simplified stub DSL
        self._run_stub_dsl(script_text, ctx)
        ctx.add_trace(node.id, "exit", "groovy script executed")
        return ctx

    def _load_script(self, node: FlowNode, ctx: MessageContext) -> str:
        if node.config.get("script"):
            return node.config["script"]
        # Resource lookup: walk the trace's project resources via the message context.
        # The test harness injects the project's resource map into ctx.variables['__resources__'].
        resource_path = node.config.get("resource")
        resources = ctx.variables.get("__resources__", {})
        content = resources.get(resource_path)
        if content is None:
            raise FileNotFoundError(f"groovy resource not found: {resource_path}")
        return content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)

    def _run_stub_dsl(self, script_text: str, ctx: MessageContext) -> None:
        """Interpret a tiny subset of Groovy-like statements.

        Supported forms (line-based, very small):
          message.setHeader('X', 'value')
          message.setProperty('Y', 'value')
          message.setBody('text')
          def json = new JsonSlurper().parseText(message.getBody())
          // (no-op for unsupported constructs)
        """
        for raw_line in script_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("//") or line.startswith("/*"):
                continue
            m = re.match(r"message\.setHeader\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)", line)
            if m:
                ctx.headers[m.group(1)] = m.group(2)
                continue
            m = re.match(r"message\.setProperty\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)", line)
            if m:
                ctx.properties[m.group(1)] = m.group(2)
                continue
            m = re.match(r"message\.setBody\(\s*['\"](.*)['\"]\s*\)", line)
            if m:
                ctx.body = m.group(1).encode("utf-8")
                continue
            # JsonSlurper etc. — no-op in stub
            # Unknown lines are ignored (sandbox safe)

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "simulated", "target_profiles": ["sap-cloud-integration-2026-07"]}

    def security_classification(self) -> str:
        return "SANDBOXED"


register(GroovyScript())
