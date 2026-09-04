"""XSLT transform step.

Spec ref: §9.4 (`transform.xslt`, fidelity=compatible-subset, Saxon-HE XSLT 2.0 subset).

B-2 (2026-09-03): the Saxon-HE JVM bridge is live — XSLT 2.0 executes via
`services/runtime-worker-jvm/oiw-xslt-runner.sh` (process-isolated,
timeout-enforced; protocol mirrors the Groovy bridge). lxml (XSLT 1.0)
remains the fallback when the JVM bridge is unavailable (e.g. CI without
the JDK), and the runtime NOTES the fallback per step — fidelity is only
"compatible-subset" when the Saxon path executes; the lxml path is the
XSLT-1-only subset (honest, per spec §4.3).
"""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from typing import Any

from ...project import FlowNode
from ..context import MessageContext
from .base import StepPlugin, register


def _find_xslt_bridge() -> str | None:
    """Locate the oiw-xslt-runner.sh wrapper — only if RUNNABLE.

    Same CI lesson as the groovy finder (2026-09-04): verify java +
    compiled XsltRunner classes + Saxon jar, else return None so callers
    use the honest lxml-XSLT1 fallback instead of a broken subprocess.
    """
    import os
    import shutil

    oiw_home = os.environ.get("OIW_HOME")
    root = Path(oiw_home) if oiw_home else None
    if root and not (root / "services" / "runtime-worker-jvm" / "oiw-xslt-runner.sh").exists():
        root = None
    if root is None:
        root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
    path = root / "services" / "runtime-worker-jvm" / "oiw-xslt-runner.sh"
    if not path.exists():
        return None
    build = root / "services" / "runtime-worker-jvm" / "build" / "io"
    libs = root / "services" / "runtime-worker-jvm" / "lib"
    if not build.is_dir():
        return None
    if not any(libs.glob("Saxon-HE-*.jar")):
        return None
    if shutil.which("java") is None:
        return None
    return str(path)


def _run_saxon(stylesheet_bytes: bytes, body_bytes: bytes, timeout_ms: int = 30000) -> bytes:
    """Apply the stylesheet via the Saxon-HE JVM bridge. Raises on failure."""
    import tempfile

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".xsl", delete=False, encoding=None) as f:
        f.write(stylesheet_bytes)
        style_path = f.name
    try:
        payload = json.dumps(
            {
                "stylesheetPath": style_path,
                "message": {
                    "body": base64.b64encode(body_bytes).decode("ascii"),
                    "contentType": "application/xml",
                    "headers": {},
                    "properties": {},
                },
                "timeoutMs": timeout_ms,
            }
        )
        r = subprocess.run(
            ["bash", _find_xslt_bridge()],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000 + 10,
        )
        out = json.loads(r.stdout.strip().splitlines()[-1])
        if out.get("status") != "COMPLETED":
            err = out.get("error") or {}
            raise RuntimeError(f"saxon bridge: {err.get('type')}: {err.get('message')}")
        return base64.b64decode(out["message"]["body"])
    finally:
        Path(style_path).unlink(missing_ok=True)


class XsltTransform(StepPlugin):
    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "transform.xslt",
            "name": "XSLT Transform (Saxon-HE XSLT 2.0 via JVM bridge; lxml 1.0 fallback)",
            "description": "Applies an XSLT stylesheet to the message body (XML).",
        }

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "resource": {"type": "string", "description": "Path to .xsl file under resources/mappings/."},
            },
            "required": ["resource"],
        }

    def validate(self, node: FlowNode) -> list[str]:
        errors: list[str] = []
        if not node.config.get("resource"):
            errors.append(f"OIW-E001: xslt node '{node.id}' must specify 'resource'")
        return errors

    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        ctx.add_trace(node.id, "enter", "applying XSLT transform")
        resource_path = node.config["resource"]
        resources = ctx.variables.get("__resources__", {})
        xslt_bytes = resources.get(resource_path)
        if xslt_bytes is None:
            raise FileNotFoundError(f"XSLT resource not found: {resource_path}")
        if isinstance(xslt_bytes, str):
            xslt_bytes = xslt_bytes.encode("utf-8")

        # Saxon-HE first (XSLT 2.0 subset — the honest compatible-subset path)
        if _find_xslt_bridge() is not None:
            try:
                ctx.body = _run_saxon(xslt_bytes, ctx.body)
                ctx.headers["Content-Type"] = "application/xml"
                ctx.add_trace(node.id, "exit", "XSLT 2.0 applied via Saxon-HE JVM bridge")
                return ctx
            except Exception as exc:
                ctx.exchange_status = "FAILED"
                ctx.exception = exc
                ctx.add_trace(node.id, "error", f"Saxon bridge XSLT error: {exc}")
                return ctx

        # lxml fallback (XSLT 1.0 only) — the bridge is unavailable; honest
        # downgrade, noted per step.
        try:
            from lxml import etree

            ctx.add_trace(node.id, "note", "Saxon bridge unavailable — lxml XSLT 1.0 fallback")
            xslt_doc = etree.fromstring(xslt_bytes)
            transform = etree.XSLT(xslt_doc)
            source = etree.fromstring(ctx.body)
            result = transform(source)
            ctx.body = str(result).encode("utf-8")
            ctx.headers["Content-Type"] = "application/xml"
            ctx.add_trace(node.id, "exit", "XSLT 1.0 applied (fallback)")
        except Exception as exc:
            ctx.exchange_status = "FAILED"
            ctx.exception = exc
            ctx.add_trace(node.id, "error", f"XSLT error: {exc}")
        return ctx

    def compatibility(self) -> dict[str, Any]:
        # The engine's real-mode gate refuses simulated-fidelity steps. With
        # the Saxon bridge available the XSLT-2.0 subset executes for real;
        # fidelity is declared dynamically so the gate sees the truth of THIS
        # environment (bridge present -> compatible-subset; absent -> the
        # XSLT-1-only fallback is simulated-grade, per the original honesty
        # downgrade note).
        bridge = _find_xslt_bridge() is not None
        return {
            "fidelity": "compatible-subset" if bridge else "simulated",
            "target_profiles": ["sap-cloud-integration-2026-07"],
            "note": (
                "Saxon-HE XSLT 2.0 subset via the JVM bridge (B-2, 2026-09-03); "
                + (
                    "bridge available — compatible-subset."
                    if bridge
                    else "bridge NOT available in this environment — XSLT-1-only "
                    "lxml fallback, which is NOT a compatible subset of real SAP "
                    "CPI mappings (honesty floor, spec §4.3)."
                )
            ),
        }

    def security_classification(self) -> str:
        return "SANDBOXED"


register(XsltTransform())
