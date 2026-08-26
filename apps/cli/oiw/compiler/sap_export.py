"""CPI designtime bundle exporter (Phase 4 / hands-free roadmap).

IR → SAP CPI designtime ZIP. Structure proven against a REAL tenant
(AdaequareGST/open_mateo_test, 2026-08-25): the Integration Content API
accepts POST /IntegrationDesigntimeArtifacts with base64 ArtifactContent
and validates that the ZIP contains a manifest-bearing iFlow project.

Bundle layout mirrors packages/test-fixtures/real-sap/source-with-groovy.zip:
    .project
    META-INF/MANIFEST.MF
    src/main/resources/parameters.prop
    src/main/resources/scenarioflows/integrationflow/<flow>.iflw

The .iflw is BPMN2 with ifl extensions. Element shapes follow the real
fixture exactly (EndpointSender/EndpointRecevier [SAP's spelling]
participants, messageFlows for adapters, callActivity activityType per
the parser's _ACTIVITY_TYPE_MAP inverted). Fidelity honesty: this MVP
covers the common linear shapes; anything else raises instead of
emitting a broken bundle.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

# Inverse of sap_flow_parser._ACTIVITY_TYPE_MAP (oiw type → SAP activityType).
_OIW_TO_ACTIVITY = {
    "modifier.content": "Enricher",
    "transform.xslt": "Mapping",
    "script.groovy": "Script",
    "converter.xml-to-json": "XmlToJsonConverter",
    "converter.json-to-xml": "JsonToXmlConverter",
    "filter": "Filter",
    "router.content-based": "ExclusiveGateway",
    "splitter.general": "Splitter",
    "gather": "Gather",
    "encoder.base64": "Base64Encoder",
    "log.message": "Logger",
}

_DEFINITIONS_OPEN = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<bpmn2:definitions xmlns:bpmn2="http://www.omg.org/spec/BPMN/20100524/MODEL" '
    'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
    'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
    'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
    'xmlns:ifl="http:///com.sap.ifl.model/Ifl.xsd" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" id="Definitions_1">'
)


def _props(pairs: list[tuple[str, str]]) -> str:
    out = ["<bpmn2:extensionElements>"]
    for k, v in pairs:
        out.append(f"<ifl:property><key>{escape(k)}</key><value>{escape(v)}</value></ifl:property>")
    out.append("</bpmn2:extensionElements>")
    return "".join(out)


def export_flow_to_iflw(flow: dict) -> str:
    """Export one OIW IntegrationFlow dict to .iflw BPMN2 text."""
    spec = flow["spec"]
    flow_id = flow.get("metadata", {}).get("id", "flow")
    entrypoints = spec.get("entrypoints", [])
    nodes = spec.get("nodes", [])
    if len(entrypoints) != 1:
        raise ValueError(f"exporter MVP supports exactly one entrypoint, found {len(entrypoints)}")

    entry = entrypoints[0]
    receivers = [n for n in nodes if n["type"].startswith("receiver.")]

    parts: list[str] = [_DEFINITIONS_OPEN]

    # Collaboration + participants
    parts.append('<bpmn2:collaboration id="Collaboration_1" name="Default Collaboration">')
    parts.append(
        _props(
            [
                ("namespaceMapping", ""),
                ("allowedHeaderList", ""),
                ("ServerTrace", "false"),
                ("returnExceptionToSender", "true"),
            ]
        )
    )
    parts.append(
        f'<bpmn2:participant id="Participant_Sender" ifl:type="EndpointSender" name="{escape(flow_id)}">'
    )
    parts.append(_props([("ifl:type", "EndpointSender")]))
    parts.append("</bpmn2:participant>")
    for r in receivers:
        parts.append(
            f'<bpmn2:participant id="Participant_{escape(r["id"])}" ifl:type="EndpointRecevier" name="{escape(r["id"])}">'
            + _props([("ifl:type", "EndpointRecevier")])
            + "</bpmn2:participant>"
        )
    # Sender message flow: Participant_Sender → StartEvent_1
    path = str((entry.get("config") or {}).get("path", "/"))
    proto = "HTTPS"  # sender.http in OIW is HTTP(S) ingress on CPI
    parts.append(
        '<bpmn2:messageFlow id="MessageFlow_Sender" name="HTTPS" sourceRef="Participant_Sender" targetRef="StartEvent_1">'
        + _props(
            [
                ("ComponentType", proto),
                ("urlPath", path),
                ("Name", "HTTPS"),
                ("TransportProtocol", proto),
                ("direction", "Sender"),
                ("system", escape(flow_id)),
            ]
        )
        + "</bpmn2:messageFlow>"
    )

    # Main process
    parts.append('<bpmn2:process id="Process_1" name="Integration Process">')
    parts.append(_props([("transactionTimeout", "30"), ("componentVersion", "1.1")]))
    parts.append(
        '<bpmn2:startEvent id="StartEvent_1" name="Start">'
        + _props([("activityType", "StartEvent")])
        + "<bpmn2:outgoing>Flow_Start</bpmn2:outgoing><bpmn2:messageEventDefinition/></bpmn2:startEvent>"
    )

    prev_ref = "StartEvent_1"
    for i, node in enumerate(nodes):
        nid = f"Step_{i}_{escape(node['id'])}"
        ntype = node["type"]
        cfg = node.get("config") or {}
        if ntype.startswith("receiver."):
            url = str(cfg.get("url", ""))
            method = str(cfg.get("method", "GET"))
            parts.append(
                f'<bpmn2:serviceTask id="{nid}" name="{escape(node["id"])}">'
                + _props([("activityType", "ExternalCall"), ("componentVersion", "1.0")])
                + f"<bpmn2:incoming>Flow_{i}</bpmn2:incoming><bpmn2:outgoing>Flow_{i}_x</bpmn2:outgoing></bpmn2:serviceTask>"
            )
            parts.append(
                f'<bpmn2:messageFlow id="MessageFlow_{i}" name="HTTP" sourceRef="{nid}" targetRef="Participant_{escape(node["id"])}">'
                + _props(
                    [
                        ("ComponentType", "HTTP"),
                        ("httpMethod", method),
                        ("httpAddressWithoutQuery", url),
                        ("Name", "HTTP"),
                        ("TransportProtocol", "HTTP"),
                        ("direction", "Receiver"),
                        ("system", escape(node["id"])),
                    ]
                )
                + "</bpmn2:messageFlow>"
            )
        elif ntype == "router.content-based":
            raise ValueError("router export: use exclusiveGateway routes — not yet supported by MVP exporter")
        else:
            activity = _OIW_TO_ACTIVITY.get(ntype)
            if activity is None:
                raise ValueError(
                    f"no CPI mapping for OIW node type '{ntype}' — refusing to emit a broken bundle"
                )
            extra: list[tuple[str, str]] = []
            if ntype == "log.message":
                extra = [("bodyType", "constant"), ("wrapContent", str(cfg.get("message", "")))]
            parts.append(
                f'<bpmn2:callActivity id="{nid}" name="{escape(node["id"])}">'
                + _props(
                    [
                        *extra,
                        ("activityType", activity),
                        ("componentVersion", "1.0"),
                    ]
                )
                + f"<bpmn2:incoming>Flow_{i}</bpmn2:incoming><bpmn2:outgoing>Flow_{i}_x</bpmn2:outgoing></bpmn2:callActivity>"
            )
        parts.append(f'<bpmn2:sequenceFlow id="Flow_{i}" sourceRef="{prev_ref}" targetRef="{nid}"/>')
        prev_ref = f"{nid}_x"

    parts.append(
        '<bpmn2:endEvent id="EndEvent_1" name="End">'
        + _props([("activityType", "EndEvent")])
        + f"<bpmn2:incoming>{prev_ref}</bpmn2:incoming><bpmn2:messageEventDefinition/></bpmn2:endEvent>"
    )
    parts.append(f'<bpmn2:sequenceFlow id="{prev_ref}" sourceRef="{prev_ref}" targetRef="EndEvent_1"/>')
    parts.append("</bpmn2:process></bpmn2:definitions>")
    return "".join(parts)


# Field set mirrors what a tenant-created iFlow bundle actually contains
# (live-proven 2026-08-25: richer Import-Package manifests are fine but
# unnecessary; metainfo.prop must exist; SymbolicName needs singleton).
_MANIFEST_TEMPLATE = """Manifest-Version: 1.0
Bundle-ManifestVersion: 2
Bundle-Name: {name}
Bundle-SymbolicName: {symbolic};singleton:=true
Bundle-Version: 1.0.0
SAP-BundleType: IntegrationFlow
SAP-NodeType: IFLMAP
SAP-RuntimeProfile: iflmap
"""


def cpi_bundle_identity(existing_zip: bytes) -> tuple[str, str]:
    """Extract (Bundle-SymbolicName, iflw filename) from an existing bundle.

    UPDATES on the tenant are only accepted when the new bundle keeps the
    existing artifact's Bundle-SymbolicName (live-proven 2026-08-25:
    mismatch ⇒ HTTP 400). Callers downloading the current artifact first
    can inherit its identity instead of guessing.
    """
    import io as _io
    import zipfile as _zf

    with _zf.ZipFile(_io.BytesIO(existing_zip)) as zf:
        names = zf.namelist()
        symbolic = None
        for n in names:
            if n.endswith("META-INF/MANIFEST.MF") or n == "META-INF/MANIFEST.MF":
                for line in zf.read(n).decode("utf-8", "replace").splitlines():
                    if line.startswith("Bundle-SymbolicName:"):
                        symbolic = line.split(":", 1)[1].strip().split(";")[0]
                        break
            if symbolic:
                break
        iflw = next(
            (
                n.rsplit("/", 1)[-1]
                for n in names
                if "scenarioflows/integrationflow/" in n and n.endswith(".iflw")
            ),
            None,
        )
    if not symbolic or not iflw:
        raise ValueError("existing bundle lacks MANIFEST.MF Bundle-SymbolicName or an .iflw entry")
    return symbolic, iflw


def build_cpi_bundle(
    flow: dict, symbolic_name: str | None = None, iflw_name: str | None = None
) -> tuple[bytes, str]:
    """Build the designtime ZIP for one flow. Returns (bytes, sha256hex).

    `symbolic_name`/`iflw_name`: inherit from an existing artifact when
    UPDATING it (see cpi_bundle_identity); defaults derive from flow id.
    """
    import hashlib

    flow_id = flow.get("metadata", {}).get("id", "flow")
    symbolic = symbolic_name or flow_id.replace("-", "_").replace(".", "_")
    iflw_file = Path(iflw_name or f"{flow_id}.iflw").name
    iflw = export_flow_to_iflw(flow)

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        entries = {
            ".project": (
                '<?xml version="1.0" encoding="UTF-8"?><projectDescription>'
                f"<name>{escape(symbolic)}</name><comment/><projects/>"
                "<buildSpec/><natures>"
                "<nature>com.sap.ide.ifl.project-support.project.nature</nature>"
                "<nature>com.sap.ide.ifl.bsn</nature></natures></projectDescription>"
            ),
            "META-INF/MANIFEST.MF": _MANIFEST_TEMPLATE.format(symbolic=escape(symbolic), name=escape(flow_id)),
            "metainfo.prop": "",
            f"src/main/resources/scenarioflows/integrationflow/{iflw_file}": iflw,
        }
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, entries[name])
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()


__all__ = ["build_cpi_bundle", "export_flow_to_iflw"]
