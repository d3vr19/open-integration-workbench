"""Exporter script-resource tests (P5a iteration: Groovy in the chain).

Real exports carry Groovy sources at src/main/resources/script/<basename>
and the Script callActivity's `script` property names that file. Exporter
must refuse to emit a Script step it cannot back with a resource.
"""

from __future__ import annotations

import io
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.compiler.sap_export import (  # noqa: E402
    build_cpi_bundle,
    export_flow_to_iflw,
)

SCRIPT = """def processData(Message message) {
    message.setHeader('oiwProcessed', 'true')
    return message
}
"""


def _flow() -> dict:
    return {
        "metadata": {"id": "t", "name": "t", "version": 1},
        "spec": {
            "edges": [{"from": "s", "to": "x"}],
            "entrypoints": [{"id": "s", "type": "sender.http", "config": {"path": "/t", "methods": ["GET"]}}],
            "nodes": [
                {
                    "id": "x",
                    "type": "script.groovy",
                    "config": {"resource": "scripts/weather_transform.groovy"},
                }
            ],
        },
    }


def test_script_resource_emitted_into_bundle(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "weather_transform.groovy").write_text(SCRIPT)
    archive, _ = build_cpi_bundle(_flow(), project_root=tmp_path)
    z = zipfile.ZipFile(io.BytesIO(archive))
    entry = "src/main/resources/script/weather_transform.groovy"
    assert entry in z.namelist()
    assert z.read(entry).decode() == SCRIPT


def test_iflw_script_prop_matches_resource_basename(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "weather_transform.groovy").write_text(SCRIPT)
    xml = export_flow_to_iflw(_flow(), project_root=tmp_path)
    root = ET.fromstring(xml)
    ns = {"b": "http://www.omg.org/spec/BPMN/20100524/MODEL", "i": "http:///com.sap.ifl.model/Ifl.xsd"}
    props = {}
    for ca in root.findall(".//b:callActivity", ns):
        ee = ca.find("b:extensionElements", ns)
        props = {p.findtext("key", "", ns): p.findtext("value", "", ns) for p in ee.findall("i:property", ns)}
        if props.get("activityType") == "Script":
            break
    assert props["activityType"] == "Script"
    assert props["script"] == "weather_transform.groovy"
    assert props["scriptFunction"] == "processData"


def test_missing_project_root_refused():
    with pytest.raises(ValueError, match="project_root"):
        export_flow_to_iflw(_flow())


def test_missing_script_file_refused(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        build_cpi_bundle(_flow(), project_root=tmp_path)


def test_missing_config_resource_refused():
    flow = _flow()
    flow["spec"]["nodes"][0]["config"] = {}
    with pytest.raises(ValueError, match="config.resource"):
        export_flow_to_iflw(flow, project_root=Path("."))
