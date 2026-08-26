"""Hardening guards (Phase 0).

1. Endpoint-collision detection: paths are tenant-global; a collision
   surfaces as runtime ERROR indistinguishable from content failure.
2. Designer-open gate: every exported bundle must round-trip through our
   own BPMN parser with complete DI coverage — unopenable bundles fail
   here instead of failing a human in the web designer.
"""

from __future__ import annotations

import io
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.compiler.sap_export import build_cpi_bundle  # noqa: E402
from oiw.compiler.sap_flow_parser import parse_bpmn2_iflw  # noqa: E402
from oiw.tenant.collisions import (  # noqa: E402
    PathClaim,
    extract_https_paths,
    find_collisions,
)

DI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
B_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"


# ---------- collision guard ----------


def test_extract_https_paths():
    xml = (
        "<bpmn2:messageFlow><bpmn2:extensionElements>"
        "<ifl:property><key>urlPath</key><value>/weather</value></ifl:property>"
        "</bpmn2:extensionElements></bpmn2:messageFlow>"
    )
    assert extract_https_paths(xml) == ["/weather"]


def test_find_collisions_excludes_target_and_normalizes_slash():
    claims = [
        PathClaim("other", "1.0.0", "/oiw_pd_hf"),
        PathClaim("other", "1.0.0", "/other"),
        PathClaim("target", "1.0.0", "/oiw_pd_hf"),
    ]
    hits = find_collisions(claims, "/oiw_pd_hf/", exclude_artifact_id="target")
    assert [h.artifact_id for h in hits] == ["other"]
    assert find_collisions(claims, "/free", exclude_artifact_id="target") == []


# ---------- designer-open gate ----------


def _bundle_xml(**kwargs) -> str:
    archive, _ = build_cpi_bundle(**kwargs)
    z = zipfile.ZipFile(io.BytesIO(archive))
    return z.read([n for n in z.namelist() if n.endswith(".iflw")][0]).decode()


def _assert_designer_open(xml: str) -> None:
    """Round-trip + DI completeness: the two things the designer needs."""
    parsed = parse_bpmn2_iflw(xml)  # must not raise
    assert parsed

    root = ET.fromstring(xml)
    plane = root.find(f".//{{{DI_NS}}}BPMNDiagram/{{{DI_NS}}}BPMNPlane")
    assert plane is not None, "missing BPMNDiagram section — designer cannot render"

    shaped = {s.get("bpmnElement") for s in plane.findall(f"{{{DI_NS}}}BPMNShape")}
    edged = {e.get("bpmnElement") for e in plane.findall(f"{{{DI_NS}}}BPMNEdge")}
    collab = root.find(f"{{{B_NS}}}collaboration")
    process = root.find(f"{{{B_NS}}}process")

    flow_elements = set()
    for el in list(collab) + list(process):
        tag = el.tag.split("}")[-1]
        if tag in ("participant", "startEvent", "endEvent", "task", "serviceTask", "callActivity"):
            flow_elements.add(el.get("id"))

    missing_shapes = {i for i in flow_elements if i not in shaped and not i.startswith("SequenceFlow")}
    assert not missing_shapes, f"elements without BPMNShape: {sorted(missing_shapes)}"
    seq_ids = {el.get("id") for el in process.findall(f"{{{B_NS}}}sequenceFlow")}
    mf_ids = {el.get("id") for el in collab.findall(f"{{{B_NS}}}messageFlow")}
    assert seq_ids <= edged, f"sequenceFlows without BPMNEdge: {sorted(seq_ids - edged)}"
    assert mf_ids <= edged, f"messageFlows without BPMNEdge: {sorted(mf_ids - edged)}"


def test_gate_bare_passthrough(tmp_path):
    flow = {
        "metadata": {"id": "bare", "version": 1},
        "spec": {
            "edges": [],
            "entrypoints": [{"id": "s", "type": "sender.http", "config": {"path": "/b", "methods": ["GET"]}}],
            "nodes": [],
        },
    }
    _assert_designer_open(_bundle_xml(flow=flow, project_root=tmp_path))


def test_gate_full_v6_chain(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "g.groovy").write_text("def processData(m){return m}\n")
    flow = {
        "metadata": {"id": "chain", "version": 1},
        "spec": {
            "edges": [
                {"from": "s", "to": "rr"},
                {"from": "rr", "to": "gx"},
                {"from": "gx", "to": "pd"},
            ],
            "entrypoints": [{"id": "s", "type": "sender.http", "config": {"path": "/c", "methods": ["GET"]}}],
            "nodes": [
                {
                    "id": "rr",
                    "type": "receiver.http",
                    "config": {"url": "https://api.example.com/v1?x=1", "method": "GET"},
                },
                {"id": "gx", "type": "script.groovy", "config": {"resource": "scripts/g.groovy"}},
                {"id": "pd", "type": "receiver.processdirect", "config": {"address": "/oiw_pd"}},
            ],
        },
    }
    _assert_designer_open(_bundle_xml(flow=flow, project_root=tmp_path))


def test_gate_pd_listener(tmp_path):
    flow = {
        "metadata": {"id": "listener", "version": 1},
        "spec": {
            "edges": [{"from": "pd-in", "to": "wv"}],
            "entrypoints": [
                {"id": "pd-in", "type": "sender.processdirect", "config": {"address": "/oiw_pd_hf"}}
            ],
            "nodes": [
                {
                    "id": "wv",
                    "type": "variables.write",
                    "config": {"name": "oiw_var", "value": "${body}", "encrypt": True},
                }
            ],
        },
    }
    _assert_designer_open(_bundle_xml(flow=flow, project_root=tmp_path))
