"""Exporter v6 shape tests: Request-Reply, ProcessDirect receiver, Variables.

All shapes mirrored from UI-authored reference exports (testing_oiw v3 +
oiw_pd, 2026-08-26) and validated live on the tenant.
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

from oiw.compiler.sap_export import build_cpi_bundle, export_flow_to_iflw  # noqa: E402

NS = {
    "b": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "i": "http:///com.sap.ifl.model/Ifl.xsd",
}
GROOVY = "def processData(Message m) { return m }\n"


def _entry(path="/t"):
    return {"id": "s", "type": "sender.http", "config": {"path": path, "methods": ["GET"]}}


def _parse(xml):
    return ET.fromstring(xml)


def _mfs(root):
    out = {}
    for mf in root.findall(f".//{{{NS['b']}}}messageFlow"):
        ee = mf.find(f"{{{NS['b']}}}extensionElements")
        props = (
            {p.findtext("key", ""): p.findtext("value", "") for p in ee.findall(f"{{{NS['i']}}}property")}
            if ee is not None
            else {}
        )
        out[mf.get("name")] = (mf, props)
    return out


def test_midflow_http_renders_request_reply(tmp_path):
    flow = {
        "metadata": {"id": "t", "version": 1},
        "spec": {
            "edges": [],
            "entrypoints": [_entry()],
            "nodes": [
                {
                    "id": "rr",
                    "type": "receiver.http",
                    "config": {"url": "https://api.example.com/v1?x=1", "method": "GET"},
                },
                {"id": "log-after", "type": "log.message", "config": {"message": "got it"}},
            ],
        },
    }
    root = _parse(export_flow_to_iflw(flow, project_root=tmp_path))
    tasks = root.findall(".//b:serviceTask", NS)
    assert len(tasks) == 1
    ee = tasks[0].find("b:extensionElements", NS)
    props = {p.findtext("key", ""): p.findtext("value", "") for p in ee.findall(f"{{{NS['i']}}}property")}
    assert props["activityType"] == "ExternalCall"
    # messageFlow wires the ServiceTask to the receiver participant
    mf, mprops = _mfs(root)["HTTP"]
    assert mf.get("sourceRef") == tasks[0].get("id")
    assert mprops["httpAddressWithoutQuery"] == "https://api.example.com/v1"
    assert mprops["httpAddressQuery"] == "x=1"
    # the flow CONTINUES after the request-reply (log step follows)
    procs = root.findall(".//b:callActivity", NS)
    assert any(c.get("name") == "log-after" for c in procs)


def test_processdirect_terminal_receiver(tmp_path):
    flow = {
        "metadata": {"id": "t", "version": 1},
        "spec": {
            "edges": [],
            "entrypoints": [_entry()],
            "nodes": [{"id": "pd-out", "type": "receiver.processdirect", "config": {"address": "/oiw_pd"}}],
        },
    }
    xml = export_flow_to_iflw(flow, project_root=tmp_path)
    root = _parse(xml)
    mf, props = _mfs(root)["ProcessDirect"]
    assert mf.get("sourceRef") == "EndEvent_1"
    assert props["ComponentType"] == "ProcessDirect"
    assert props["address"] == "/oiw_pd"
    assert props["direction"] == "Receiver"
    assert props["Vendor"] == "SAP"


def test_processdirect_midflow_refused():
    flow = {
        "metadata": {"id": "t", "version": 1},
        "spec": {
            "edges": [],
            "entrypoints": [_entry()],
            "nodes": [
                {"id": "pd", "type": "receiver.processdirect", "config": {"address": "/x"}},
                {"id": "after", "type": "log.message", "config": {}},
            ],
        },
    }
    with pytest.raises(ValueError, match="request-reply"):
        export_flow_to_iflw(flow, project_root=Path("."))


def test_variables_write_row_xml():
    flow = {
        "metadata": {"id": "t", "version": 1},
        "spec": {
            "edges": [],
            "entrypoints": [_entry()],
            "nodes": [
                {
                    "id": "wv",
                    "type": "variables.write",
                    "config": {"name": "oiw_var", "value": "$in.body", "encrypt": True},
                }
            ],
        },
    }
    root = _parse(export_flow_to_iflw(flow))
    ca = root.findall(".//b:callActivity", NS)[-1]
    ee = ca.find("b:extensionElements", NS)
    props = {p.findtext("key", ""): p.findtext("value", "") for p in ee.findall(f"{{{NS['i']}}}property")}
    assert props["activityType"] == "Variables"
    assert props["variable"] == (
        "<row><cell>oiw_var</cell><cell></cell><cell>expression</cell>"
        "<cell>$in.body</cell><cell>global</cell></row>"
    )
    assert props["encrypt"] == "true"


def test_full_chain_bundle(tmp_path):
    """The operator's target topology: HTTPS -> RR(open-meteo) -> groovy -> PD."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "weather_transform.groovy").write_text(GROOVY)
    flow = {
        "metadata": {"id": "chain", "version": 1},
        "spec": {
            "edges": [
                {"from": "s", "to": "rr"},
                {"from": "rr", "to": "gx"},
                {"from": "gx", "to": "pd"},
            ],
            "entrypoints": [_entry("/oiw_pd_hf")],
            "nodes": [
                {
                    "id": "rr",
                    "type": "receiver.http",
                    "config": {
                        "url": "https://api.open-meteo.com/v1/forecast?latitude=52.52&longitude=13.41&current=temperature_2m",
                        "method": "GET",
                    },
                },
                {
                    "id": "gx",
                    "type": "script.groovy",
                    "config": {"resource": "scripts/weather_transform.groovy"},
                },
                {"id": "pd", "type": "receiver.processdirect", "config": {"address": "/oiw_pd"}},
            ],
        },
    }
    archive, _ = build_cpi_bundle(flow, project_root=tmp_path)
    z = zipfile.ZipFile(io.BytesIO(archive))
    xml = z.read([n for n in z.namelist() if n.endswith(".iflw")][0]).decode()
    root = _parse(xml)
    kinds = [
        el.tag.split("}")[-1]
        for el in root.find(f"{{{NS['b']}}}process")
        if not el.tag.endswith("extensionElements")
    ]
    assert "serviceTask" in kinds  # request-reply task present
    assert "endEvent" in kinds  # terminal PD end event
    assert "src/main/resources/script/weather_transform.groovy" in z.namelist()


def test_diagram_section_covers_every_element(tmp_path):
    """Designer-open requirement: every node/participant/flow needs DI."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "g.groovy").write_text(GROOVY)
    flow = {
        "metadata": {"id": "t", "version": 1},
        "spec": {
            "edges": [],
            "entrypoints": [_entry("/p")],
            "nodes": [
                {
                    "id": "rr",
                    "type": "receiver.http",
                    "config": {"url": "https://a.example.com/x", "method": "GET"},
                },
                {"id": "gx", "type": "script.groovy", "config": {"resource": "scripts/g.groovy"}},
                {"id": "pd", "type": "receiver.processdirect", "config": {"address": "/oiw_pd"}},
            ],
        },
    }
    xml = export_flow_to_iflw(flow, project_root=tmp_path)
    root = _parse(xml)
    plane = root.find(".//{http://www.omg.org/spec/BPMN/20100524/DI}BPMNPlane")
    assert plane is not None
    shaped = {
        s.get("bpmnElement") for s in plane.findall("{http://www.omg.org/spec/BPMN/20100524/DI}BPMNShape")
    }
    edged = {
        e.get("bpmnElement") for e in plane.findall("{http://www.omg.org/spec/BPMN/20100524/DI}BPMNEdge")
    }
    for pid in (
        "StartEvent_1",
        "EndEvent_1",
        "ServiceTask_1",
        "CallActivity_2",
        "Participant_1",
        "Participant_rr",
        "Participant_pd",
        "Participant_Process_1",
    ):
        assert pid in shaped, pid
    assert {
        "SequenceFlow_0",
        "SequenceFlow_1",
        "SequenceFlow_2",
        "MessageFlow_1",
        "MessageFlow_R1",
        "MessageFlow_R3",
    } <= edged


def test_processdirect_sender_entrypoint():
    """Listener flows (oiw_pd_hf role): PD sender + variables.write."""
    flow = {
        "metadata": {"id": "t", "version": 1},
        "spec": {
            "edges": [{"from": "s", "to": "wv"}],
            "entrypoints": [{"id": "s", "type": "sender.processdirect", "config": {"address": "/oiw_pd_hf"}}],
            "nodes": [
                {
                    "id": "wv",
                    "type": "variables.write",
                    "config": {"name": "oiw_var", "value": "${body}", "encrypt": True},
                }
            ],
        },
    }
    xml = export_flow_to_iflw(flow)
    root = _parse(xml)
    mf, props = _mfs(root)["ProcessDirect"]
    assert mf.get("sourceRef") == "Participant_1"
    assert props["address"] == "/oiw_pd_hf"
    assert props["direction"] == "Sender"
    assert "<key>urlPath</key>" not in xml  # no HTTPS adapter residue


def test_receiver_sftp_terminal(tmp_path):
    flow = {
        "metadata": {"id": "t", "version": 1},
        "spec": {
            "edges": [],
            "entrypoints": [_entry("/sftp")],
            "nodes": [
                {
                    "id": "drop",
                    "type": "receiver.sftp",
                    "config": {
                        "host": "eu-central-1.sftpcloud.io",
                        "port": 22,
                        "directory": "/upload",
                        "filename": "oiw-e2e.txt",
                        "credentialName": "oiw-sftpcloud",
                    },
                }
            ],
        },
    }
    root = _parse(export_flow_to_iflw(flow, project_root=tmp_path))
    mf, props = _mfs(root)["SFTP"]
    assert mf.get("sourceRef") == "EndEvent_1"
    assert props["ComponentType"] == "SFTP"
    assert props["authentication"] == "user_password"
    assert props["host"] == "eu-central-1.sftpcloud.io:22"
    assert props["path"] == "/upload"
    assert props["credential_name"] == "oiw-sftpcloud"
    assert props["sftpSecEnabled"] == "1"  # adapter dialect is 0/1, not true/false


def test_receiver_sftp_requires_credential():
    flow = {
        "metadata": {"id": "t", "version": 1},
        "spec": {
            "edges": [],
            "entrypoints": [_entry()],
            "nodes": [{"id": "d", "type": "receiver.sftp", "config": {"host": "h.example.com"}}],
        },
    }
    with pytest.raises(ValueError, match="credentialName"):
        export_flow_to_iflw(flow, project_root=Path("."))


def test_multi_entrypoint_writer_plus_poller(tmp_path):
    """Complete SFTP lifecycle in ONE artifact: HTTPS writer + SFTP poller.

    Poller mirrors DPWORLD_SFTP_QAS: cron scheduleKey, filename filter,
    delete-on-fetch (no file.move/doneFileName keys).
    """
    flow = {
        "metadata": {"id": "sftp-lifecycle", "version": 1},
        "spec": {
            "edges": [
                {"from": "http-in", "to": "drop"},
                {"from": "sftp-poll", "to": "fetched-log"},
            ],
            "entrypoints": [
                {
                    "id": "http-in",
                    "type": "sender.http",
                    "config": {"path": "/oiw_sftp_test", "methods": ["POST"]},
                },
                {
                    "id": "sftp-poll",
                    "type": "sender.sftp",
                    "config": {
                        "host": "etssftp",
                        "port": 2232,
                        "directory": "../../INTERFACE/DP_WORLD",
                        "filenameFilter": "OIW-E2E.*",
                        "credentialName": "AxisBnk_dev",
                        "proxyType": "sapcc",
                        "locationId": "EMCNPCC",
                    },
                },
            ],
            "nodes": [
                {
                    "id": "drop",
                    "type": "receiver.sftp",
                    "config": {
                        "host": "etssftp",
                        "port": 2232,
                        "directory": "../../INTERFACE/DP_WORLD",
                        "filename": "OIW-E2E-${date:now:yyyyMMddHHmmss}.dat",
                        "credentialName": "AxisBnk_dev",
                        "proxyType": "sapcc",
                        "locationId": "EMCNPCC",
                    },
                },
                {"id": "fetched-log", "type": "log.message", "config": {"message": "fetched"}},
            ],
        },
    }
    xml = export_flow_to_iflw(flow)
    root = _parse(xml)

    starts = root.findall(".//b:startEvent", NS)
    assert {s.get("id") for s in starts} == {"StartEvent_1", "StartEvent_2"}

    mfs = _mfs(root)
    assert "HTTPS" in mfs and "SFTP" in mfs
    sftp_mf, sftp_props = mfs["SFTP"]
    # TWO SFTP messageFlows: writer (R1) + poller (S2)
    all_sftp = [mf for mf in root.findall(".//b:messageFlow", NS) if mf.get("name") == "SFTP"]
    assert len(all_sftp) == 2

    # poller: cron schedule + delete-on-fetch
    poller = [mf for mf in all_sftp if mf.get("sourceRef", "").startswith("Participant")][0]
    pp = {
        p.findtext("key"): p.findtext("value")
        for p in poller.find(f"{{{NS['b']}}}extensionElements").findall(f"{{{NS['i']}}}property")
    }
    assert "scheduleKey" in pp and "cron" in pp["scheduleKey"]
    assert pp["fileName"] == "OIW-E2E.*"
    # fetch + remove from poll dir: reference-proven noop=delete + .archive move
    assert pp["noop"] == "delete"
    assert pp["file.move"] == ".archive"

    # ALL main-process ends are message-typed (blood law re-proven live
    # 2026-09-02: open_mateo_test + oiw_pd_hf + oiw_pd all carry
    # MessageEndEvent on every branch; plain ends exist only in subprocesses).
    end2 = root.find(".//b:endEvent[@id='EndEvent_2']", NS)
    assert end2 is not None
    assert end2.find("b:messageEventDefinition", NS) is not None
