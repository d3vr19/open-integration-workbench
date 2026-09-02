"""Exporter receiver-address tests (P5a live bisection, 2026-08-26 + 2026-09-02).

CPI runtime-start REQUIRES the HTTP receiver address split across
httpAddressWithoutQuery and httpAddressQuery. LIVE LAW (2026-09-02,
tenant bisection on oiw_turbo_fwd): the only message-proven HTTP-call
form is Request-Reply (serviceTask mf); a TERMINAL receiver.http is
refused by the exporter (EndEvent-form fails messages with 'Member
name not found'; RR+plain-end is start-fatal). The assembler appends a
ProcessDirect terminator so HTTP receivers always render mid-flow RR.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.compiler.sap_export import export_flow_to_iflw  # noqa: E402


def _flow(url: str) -> dict:
    return {
        "metadata": {"id": "t", "name": "t", "version": 1},
        "spec": {
            "edges": [{"from": "s", "to": "r"}],
            "entrypoints": [{"id": "s", "type": "sender.http", "config": {"path": "/t", "methods": ["GET"]}}],
            "nodes": [
                {
                    "id": "r",
                    "type": "receiver.http",
                    "config": {"url": url, "method": "GET", "timeoutSeconds": 30},
                }
            ],
        },
    }


def _rr_flow(url: str) -> dict:
    """Mid-flow RR receiver (the live-proven form): sender → RR → PD end."""
    flow = _flow(url)
    flow["spec"]["nodes"].append(
        {"id": "pd", "type": "receiver.processdirect", "config": {"address": "/t_pd"}}
    )
    flow["spec"]["edges"] = [
        {"from": "s", "to": "r"},
        {"from": "r", "to": "pd"},
    ]
    return flow


def _receiver_props(xml: str) -> dict:
    root = ET.fromstring(xml)
    ns = {"b": "http://www.omg.org/spec/BPMN/20100524/MODEL", "i": "http:///com.sap.ifl.model/Ifl.xsd"}
    out = {}
    for mf in root.findall(".//b:messageFlow", ns):
        ee = mf.find("b:extensionElements", ns)
        if ee is None:
            continue
        props = {p.findtext("key", "", ns): p.findtext("value", "", ns) for p in ee.findall("i:property", ns)}
        if "httpAddressWithoutQuery" in props:
            out = props
    assert out, "receiver messageFlow not found"
    return out


def test_terminal_http_receiver_refused():
    """Terminal receiver.http is not an exportable shape (live law 2026-09-02)."""
    with pytest.raises(ValueError, match="terminal receiver.http"):
        export_flow_to_iflw(_flow("https://api.example.com/v1/x?a=1"))


def test_rr_receiver_keeps_literal_url_split():
    props = _receiver_props(export_flow_to_iflw(_rr_flow("https://api.example.com/v1/x?a=1&b=2")))
    assert props["httpAddressWithoutQuery"] == "https://api.example.com/v1/x"
    assert props["httpAddressQuery"] == "a=1&b=2"


def test_rr_receiver_without_query_keeps_query_empty():
    props = _receiver_props(export_flow_to_iflw(_rr_flow("https://api.example.com/v1/y")))
    assert props["httpAddressWithoutQuery"] == "https://api.example.com/v1/y"
    assert props["httpAddressQuery"] == ""


def test_rr_receiver_with_port_and_depth_path():
    props = _receiver_props(export_flow_to_iflw(_rr_flow("https://h:8443/a/b/c?z")))
    assert props["httpAddressWithoutQuery"] == "https://h:8443/a/b/c"
    assert props["httpAddressQuery"] == "z"
