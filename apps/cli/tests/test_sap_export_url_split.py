"""Exporter receiver-address tests (P5a live bisection, 2026-08-26).

CPI runtime-start REQUIRES the HTTP receiver address split across
httpAddressWithoutQuery (scheme+host+path) and httpAddressQuery (query
string). Folding '?query' into WithoutQuery fails runtime start — proven
by single-variable tenant bisection (p5-p6-plan.md §6).
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

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


def test_receiver_url_split_address_and_query():
    props = _receiver_props(export_flow_to_iflw(_flow("https://api.example.com/v1/x?a=1&b=2")))
    assert props["httpAddressWithoutQuery"] == "https://api.example.com/v1/x"
    assert props["httpAddressQuery"] == "a=1&b=2"


def test_receiver_url_without_query_keeps_query_empty():
    props = _receiver_props(export_flow_to_iflw(_flow("https://api.example.com/v1/y")))
    assert props["httpAddressWithoutQuery"] == "https://api.example.com/v1/y"
    assert props["httpAddressQuery"] == ""


def test_receiver_url_with_port_and_depth_path():
    props = _receiver_props(export_flow_to_iflw(_flow("https://h:8443/a/b/c?z")))
    assert props["httpAddressWithoutQuery"] == "https://h:8443/a/b/c"
    assert props["httpAddressQuery"] == "z"
