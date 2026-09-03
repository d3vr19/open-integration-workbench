"""Tests for the JVM Groovy bridge integration.

Spec ref: §9.4 (script.groovy), §9.6 (Groovy Sandbox), §16.1 threat 2.

Tests:
  1. Header set — Groovy script sets a header → assert header in output
  2. Body transform — Groovy script transforms JSON body → assert body changed
  3. Runtime.exec blocked — Groovy script with Runtime.getRuntime() → assert FAILED
  4. Timeout killed — Groovy script with infinite loop → assert timeout + process killed

These tests are skipped if the JVM bridge is not runnable (no JDK or no JARs).
In CI, setup.sh installs JDK + JARs + compiles, so tests will run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oiw.project import FlowNode
from oiw.runtime.context import MessageContext
from oiw.runtime.steps.base import get_plugin
from oiw.runtime.steps.groovy_script import _find_jvm_bridge


def _jvm_bridge_runnable() -> bool:
    """Check if the JVM bridge is actually runnable (JARs + compiled classes exist)."""
    bridge = _find_jvm_bridge()
    if bridge is None:
        return False
    bridge_dir = Path(bridge).parent
    lib_dir = bridge_dir / "lib"
    has_jars = lib_dir.is_dir() and any(
        f.name.startswith("groovy-") and f.suffix == ".jar" for f in lib_dir.iterdir()
    )
    has_classes = (bridge_dir / "build" / "io").is_dir()
    return has_jars and has_classes


# Skip JVM tests if bridge is not runnable (e.g., local dev without JDK)
# In CI, setup.sh installs JDK + JARs + compiles, so tests will run.
pytestmark = pytest.mark.skipif(
    not _jvm_bridge_runnable(),
    reason="JVM Groovy bridge not runnable — run: bash services/runtime-worker-jvm/setup.sh",
)


@pytest.fixture()
def plugin():
    return get_plugin("script.groovy")


def _make_node(script_content: str) -> FlowNode:
    return FlowNode(
        id="test-groovy",
        type="script.groovy",
        config={"script": script_content},
        fidelity="compatible-subset",
    )


def _make_ctx(body: bytes = b"{}", headers: dict | None = None) -> MessageContext:
    return MessageContext(
        body=body,
        content_type="application/json",
        headers=headers or {"Content-Type": "application/json"},
        properties={},
    )


# Test 1: Header set
def test_groovy_sets_header(plugin) -> None:
    # SAP Message API dialect (tenant corpus ground truth; the JVM bridge's
    # canonical dialect — bare `headers["k"]=v` never reached the binding,
    # a live finding 2026-09-04: Groovy script meta-properties shadow
    # binding vars).
    script = (
        "import com.sap.gateway.ip.core.customdev.util.Message\n"
        "def Message processData(Message message) {\n"
        '    message.setHeader("X-Test", "hello from groovy")\n'
        "    return message\n"
        "}"
    )
    node = _make_node(script)
    ctx = _make_ctx()
    result = plugin.execute(node, ctx, mocks={})

    assert result.exchange_status != "FAILED", f"Groovy execution failed: {result.exception}"
    assert result.headers.get("X-Test") == "hello from groovy"


# Test 2: Body transform
def test_groovy_transforms_body(plugin) -> None:
    script = """
import com.sap.gateway.ip.core.customdev.util.Message
import groovy.json.JsonSlurper
import groovy.json.JsonOutput

def Message processData(Message message) {
    def body = message.getBody(java.lang.String) as String
    def json = new JsonSlurper().parseText(body)
    json.processed = true
    message.setBody(JsonOutput.toJson(json))
    return message
}
"""
    node = _make_node(script)
    ctx = _make_ctx(b'{"orderId":"ORD-001"}')
    result = plugin.execute(node, ctx, mocks={})

    assert result.exchange_status != "FAILED", f"Groovy execution failed: {result.exception}"
    import json as _json

    output = _json.loads(result.body)
    assert output["orderId"] == "ORD-001"
    assert output["processed"] is True


# Test 3: Runtime.exec blocked
def test_groovy_blocks_runtime_exec(plugin) -> None:
    script = """
def runtime = Runtime.getRuntime()
runtime.exec("id")
"""
    node = _make_node(script)
    ctx = _make_ctx()
    result = plugin.execute(node, ctx, mocks={})

    assert result.exchange_status == "FAILED"
    error_msg = str(result.exception or "")
    assert "Runtime" in error_msg or "forbidden" in error_msg.lower() or "SecurityException" in error_msg


# Test 4: Timeout killed (uses 4s timeout via monkey-patch)
def test_groovy_timeout_killed(plugin) -> None:
    """A Groovy script with an infinite loop → timeout, subprocess killed.

    Uses a 4s timeout so the test runs fast. Verifies the JVM process
    is killed and doesn't linger.
    """
    import subprocess as sp
    import time

    # Pure Groovy infinite loop (no Thread.sleep — Thread is blocked by whitelist)
    script = "while (true) { def x = 1 + 1 }"
    node = FlowNode(
        id="test-timeout",
        type="script.groovy",
        config={"script": script},
        fidelity="compatible-subset",
    )
    ctx = _make_ctx()

    # Monkey-patch Popen.communicate to use a 4s timeout
    original_popen = sp.Popen

    class FastPopen(original_popen):
        def communicate(self, *args, **kwargs):
            kwargs["timeout"] = 4
            return super().communicate(*args, **kwargs)

    sp.Popen = FastPopen
    try:
        result = plugin.execute(node, ctx, mocks={})
    finally:
        sp.Popen = original_popen

    assert result.exchange_status == "FAILED"
    assert "timeout" in str(result.exception or "").lower()

    # Wait for process cleanup, then verify no lingering Java process
    time.sleep(0.5)
    ps = sp.run(["pgrep", "-f", "GroovyRunner"], capture_output=True, text=True)
    assert ps.stdout.strip() == "", f"Java process still running after timeout: {ps.stdout}"
