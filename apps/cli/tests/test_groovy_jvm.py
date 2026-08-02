"""Tests for the JVM Groovy bridge integration.

Spec ref: §9.4 (script.groovy), §9.6 (Groovy Sandbox), §16.1 threat 2.

Tests:
  1. Header set — Groovy script sets a header → assert header in output
  2. Body transform — Groovy script transforms JSON body → assert body changed
  3. Runtime.exec blocked — Groovy script with Runtime.getRuntime() → assert FAILED
  4. Timeout killed — Groovy script with infinite loop → assert timeout

These tests are skipped if the JVM bridge is not available (no Java or no JAR).
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
    has_jars = (bridge_dir / "lib" / "groovy-4.0.22.jar").exists()
    has_classes = (bridge_dir / "build" / "io").is_dir()
    return has_jars and has_classes


# Skip all tests if JVM bridge is not actually runnable
pytestmark = pytest.mark.skipif(
    not _jvm_bridge_runnable(),
    reason="JVM Groovy bridge not runnable — requires Java + Groovy JARs + compiled classes. "
    "Run: cd services/runtime-worker-jvm && javac -cp 'lib/*' -d build src/main/java/io/oiw/groovy/GroovyRunner.java",
)


@pytest.fixture()
def plugin():
    return get_plugin("script.groovy")


def _make_node(script_content: str) -> FlowNode:
    """Create a FlowNode with an inline Groovy script."""
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


# ---------------------------------------------------------------------
# Test 1: Header set
# ---------------------------------------------------------------------


def test_groovy_sets_header(plugin) -> None:
    """A Groovy script that sets a header → the header appears in the output context."""
    script = """
// Set a header via Groovy
headers["X-Test"] = "hello from groovy"
"""
    node = _make_node(script)
    ctx = _make_ctx()
    result = plugin.execute(node, ctx, mocks={})

    assert result.exchange_status != "FAILED", f"Groovy execution failed: {result.exception}"
    assert result.headers.get("X-Test") == "hello from groovy"


# ---------------------------------------------------------------------
# Test 2: Body transform
# ---------------------------------------------------------------------


def test_groovy_transforms_body(plugin) -> None:
    """A Groovy script that transforms the JSON body → the body is changed."""
    script = """
import groovy.json.JsonSlurper
import groovy.json.JsonOutput

def json = new JsonSlurper().parseText(body)
json.processed = true
body = JsonOutput.toJson(json)
"""
    node = _make_node(script)
    ctx = _make_ctx(b'{"orderId":"ORD-001"}')
    result = plugin.execute(node, ctx, mocks={})

    assert result.exchange_status != "FAILED", f"Groovy execution failed: {result.exception}"
    import json as _json

    output = _json.loads(result.body)
    assert output["orderId"] == "ORD-001"
    assert output["processed"] is True


# ---------------------------------------------------------------------
# Test 3: Runtime.exec blocked
# ---------------------------------------------------------------------


def test_groovy_blocks_runtime_exec(plugin) -> None:
    """A Groovy script containing Runtime.getRuntime().exec() → execution FAILED."""
    script = """
def runtime = Runtime.getRuntime()
runtime.exec("id")
"""
    node = _make_node(script)
    ctx = _make_ctx()
    result = plugin.execute(node, ctx, mocks={})

    assert result.exchange_status == "FAILED"
    # The error should mention the forbidden construct
    error_msg = str(result.exception or "")
    assert "Runtime" in error_msg or "forbidden" in error_msg.lower() or "SecurityException" in error_msg


# ---------------------------------------------------------------------
# Test 4: Timeout killed
# ---------------------------------------------------------------------


def test_groovy_timeout_killed(plugin) -> None:
    """A Groovy script with an infinite loop → timeout after 30s, subprocess killed.

    Note: This test takes ~30s to run. It verifies that the JVM process is
    killed after the timeout and doesn't linger.
    """
    script = """
while (true) { Thread.sleep(100) }
"""
    node = _make_node(script)
    ctx = _make_ctx()
    result = plugin.execute(node, ctx, mocks={})

    assert result.exchange_status == "FAILED"
    assert "timeout" in str(result.exception or "").lower()

    # Verify no lingering Java process
    import subprocess

    ps = subprocess.run(["pgrep", "-f", "oiw-groovy-runner"], capture_output=True, text=True)
    assert ps.stdout.strip() == "", f"Java process still running after timeout: {ps.stdout}"
