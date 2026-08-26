"""CPI designtime bundle exporter (Phase 4 / hands-free roadmap).

IR → SAP CPI designtime ZIP. Live-proven against AdaequareGST/
open_mateo_test (2026-08-25):

  - UPDATE verb  = PUT /IntegrationDesigntimeArtifacts(Id,V)
                   {ArtifactContent: base64 zip}; POST=create-only,
                   PUT $value/multipart = 501.
  - Identity     = updates reject Bundle-SymbolicName changes → inherit
                   from the current bundle via cpi_bundle_identity().
  - Bundle shape = minimal MANIFEST.MF (+singleton:=true), .project,
                   metainfo.prop, one .iflw under
                   src/main/resources/scenarioflows/integrationflow/.

Fidelity policy (v2): the .iflw mirrors element/property shapes from the
REAL fixture in packages/test-fixtures/real-sap/source-with-groovy.zip so
the web designer opens exported flows cleanly. Only designer-proven node
types are emitted; anything else raises instead of producing a bundle
that imports but breaks the UI (learned the hard way — v1 imported fine
and rendered the artifact unopenable).
"""

from __future__ import annotations

import hashlib
import zipfile
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

# Designer-proven mappings (present in the real fixture):
_OIW_TO_ACTIVITY = {
    "modifier.content": "Enricher",
    "log.message": "Enricher",  # CPI logs via Content Modifier; Logger unproven
    "script.groovy": "Script",
    "converter.json-to-xml": "JsonToXmlConverter",
    "variables.write": "Variables",
}

_COLLAB_PROPS = [
    ("namespaceMapping", ""),
    ("allowedHeaderList", ""),
    ("httpSessionHandling", "None"),
    ("ServerTrace", "false"),
    ("returnExceptionToSender", "true"),
    ("componentVersion", "1.2"),
    ("cmdVariantUri", "ctype::IFlowVariant/cname::IFlowConfiguration/version::1.2.1"),
]

_SENDER_PROPS = [
    ("ComponentType", "HTTPS"),
    ("Description", ""),
    ("maximumBodySize", "40"),
    ("ComponentNS", "sap"),
    ("componentVersion", "1.4"),
    ("urlPath", "{path}"),
    ("Name", "HTTPS"),
    ("TransportProtocolVersion", "1.4.1"),
    ("ComponentSWCVName", "external"),
    ("system", "{system}"),
    ("xsrfProtection", "0"),
    ("TransportProtocol", "HTTPS"),
    (
        "cmdVariantUri",
        "ctype::AdapterVariant/cname::sap:HTTPS/tp::HTTPS/mp::None/direction::Sender/version::1.4.1",
    ),
    ("userRole", "ESBMessaging.send"),
    ("senderAuthType", "RoleBased"),
    ("MessageProtocol", "None"),
    ("MessageProtocolVersion", "1.4.1"),
    ("ComponentSWCVId", "1.4.1"),
    ("direction", "Sender"),
]

_RECEIVER_PROPS = [
    ("apiName", ""),
    ("Description", ""),
    ("methodSourceExpression", ""),
    ("apiArtifactType", ""),
    ("providerAuth", ""),
    ("retryOnExceptionsTable", ""),
    ("ComponentNS", "sap"),
    ("privateKeyAlias", ""),
    ("httpMethod", "{method}"),
    ("apiprovider_location_id", ""),
    ("allowedResponseHeaders", "*"),
    ("Name", "HTTP"),
    ("internetProxyType", ""),
    ("TransportProtocolVersion", "1.20.2"),
    ("retryOnException", "false"),
    ("proxyPort", ""),
    ("ComponentSWCVName", "external"),
    ("streaming", "false"),
    ("enableMPLAttachments", "false"),
    # Retry/idle values below are the PROVEN-GOOD set observed on every
    # STARTED HTTP receiver flow on the live tenant (2026-08-26 bisection):
    # retryInterval='10000' alone fails CPI runtime-start (fixture-inherited
    # value); '5' is what UI-authored + production flows deploy with.
    ("pooledConnectionIdleTimeout", "300000"),
    ("httpAddressQuery", "{query}"),
    ("httpRequestTimeout", "{timeout}"),
    ("ComponentSWCVId", "1.20.2"),
    ("providerName", ""),
    ("allowedRequestHeaders", ""),
    ("MessageProtocol", "None"),
    ("direction", "Receiver"),
    ("ComponentType", "HTTP"),
    ("httpShouldSendBody", "false"),
    ("throwExceptionOnFailure", "true"),
    ("proxyType", "default"),
    ("componentVersion", "1.20"),
    ("retryIteration", "1"),
    ("proxyHost", ""),
    ("providerUrl", ""),
    ("retryOnConnectionFailure", "false"),
    ("system", "{system}"),
    ("authenticationMethod", "None"),
    ("locationID", "MBP"),
    ("retryInterval", "5"),
    ("TransportProtocol", "HTTP"),
    (
        "cmdVariantUri",
        "ctype::AdapterVariant/cname::sap:HTTP/tp::HTTP/mp::None/direction::Receiver/version::1.20.2",
    ),
    ("httpErrorResponseCodes", ""),
    ("credentialName", ""),
    ("apiDisplayName", ""),
    ("MessageProtocolVersion", "1.20.2"),
    ("providerRelativeUrl", ""),
    ("httpAddressWithoutQuery", "{url}"),
]

# ProcessDirect receiver messageFlow — mirrored verbatim from a UI-authored
# reference (oiw_pd, 2026-08-26). The `address` is the target process name.
_PROCESSDIRECT_RECEIVER_PROPS = [
    ("ComponentType", "ProcessDirect"),
    ("Description", ""),
    ("address", "{address}"),
    ("ComponentNS", "sap"),
    ("Vendor", "SAP"),
    ("componentVersion", "1.1"),
    ("Name", "ProcessDirect"),
    ("TransportProtocolVersion", "1.1.2"),
    ("ComponentSWCVName", "external"),
    ("system", "Receiver"),
    ("TransportProtocol", "Not Applicable"),
    (
        "cmdVariantUri",
        "ctype::AdapterVariant/cname::ProcessDirect/vendor::SAP/tp::Not Applicable/mp::Not Applicable/direction::Receiver/version::1.1.1",
    ),
    ("MessageProtocol", "Not Applicable"),
    ("MessageProtocolVersion", "1.1.2"),
    ("ComponentSWCVId", "1.1.2"),
    ("direction", "Receiver"),
]

# ProcessDirect sender messageFlow — mirrored verbatim from the UI-authored
# oiw_pd reference (the listener side of a ProcessDirect hop).
_PROCESSDIRECT_SENDER_PROPS = [
    ("ComponentType", "ProcessDirect"),
    ("Description", ""),
    ("address", "{address}"),
    ("ComponentNS", "sap"),
    ("Vendor", "SAP"),
    ("componentVersion", "1.1"),
    ("Name", "ProcessDirect"),
    ("TransportProtocolVersion", "1.1.2"),
    ("ComponentSWCVName", "external"),
    ("system", "Sender"),
    ("TransportProtocol", "Not Applicable"),
    (
        "cmdVariantUri",
        "ctype::AdapterVariant/cname::ProcessDirect/vendor::SAP/tp::Not Applicable/mp::Not Applicable/direction::Sender/version::1.1.2",
    ),
    ("MessageProtocol", "Not Applicable"),
    ("MessageProtocolVersion", "1.1.2"),
    ("ComponentSWCVId", "1.1.2"),
    ("direction", "Sender"),
]

# SFTP receiver messageFlow — mirrored from harvested UI-authored shapes
# (pattern-book/shapes/SFTP-Receiver-SAP_SFTP.yaml, user_password variant;
# 22+7 live flows use this family). Volatile fields parameterized.
_SFTP_RECEIVER_PROPS = [
    ("disconnect", "0"),
    ("fileName", "{filename}"),
    ("maximumReconnectAttempts", "3"),
    ("stepwise", "1"),
    ("fileExist", "Override"),
    ("ComponentNS", "sap"),
    ("autoCreate", "{autocreate}"),
    ("privateKeyAlias", ""),
    ("Name", "SFTP"),
    ("TransportProtocolVersion", "1.14.0"),
    ("flatten", "0"),
    ("sftpSecEnabled", "{sftpsec}"),
    ("useTempFile", "0"),
    ("ComponentSWCVName", "external"),
    ("path", "{directory}"),
    ("proxyPort", "{proxyport}"),
    ("host", "{hostport}"),
    ("connectTimeout", "10000"),
    ("fastExistsCheck", "1"),
    ("MessageProtocol", "File"),
    ("ComponentSWCVId", "1.14.0"),
    ("direction", "Receiver"),
    ("authentication", "user_password"),
    ("ComponentType", "SFTP"),
    ("fileAppendTimeStamp", "0"),
    ("credential_name", "{credentialname}"),
    ("proxyProtocol", "{proxyprotocol}"),
    ("proxyType", "{proxytype}"),
    ("proxyAlias", ""),
    ("componentVersion", "1.13"),
    ("reconnectDelay", "1000"),
    ("proxyHost", "{proxyhost}"),
    ("location_id", "{locationid}"),
    ("tempFileName", "${{file:name}}.tmp"),
    ("allowDeprecatedAlgorithms", "0"),
    ("TransportProtocol", "SFTP"),
    ("MessageProtocolVersion", "1.14.0"),
    ("username", ""),
]


def _elem_id(node_type: str, i: int) -> str:
    """BPMN element id for the i-th node — CPI's runtime compiler keys off
    prefixes (StartEvent_/CallActivity_/ServiceTask_/EndEvent_); generic ids
    import fine but fail runtime-start (H1, p5-p6-plan.md §6)."""
    if node_type.startswith("receiver."):
        return f"ServiceTask_{i}"
    if node_type == "router.content-based":
        return f"ExclusiveGateway_{i}"
    return f"CallActivity_{i}"


def _props(pairs: list[tuple[str, str]], indent: str = "                ") -> str:
    out = ["<bpmn2:extensionElements>"]
    for k, v in pairs:
        out.append(
            f"{indent}<ifl:property>\n{indent}    <key>{escape(k)}</key>\n{indent}    <value>{escape(v)}</value>\n{indent}</ifl:property>"
        )
    out.append(f"{indent}</bpmn2:extensionElements>")
    return "\n".join(out)


def _fill(template: list[tuple[str, str]], **kwargs: str) -> list[tuple[str, str]]:
    return [(k, v.format(**kwargs)) for k, v in template]


def _resolve_script_name(node: dict, project_root: Path | None) -> str:
    """Bundle-relative script file name for a script.groovy node.

    Mirrors real exports: resources live at src/main/resources/script/
    <basename> and the callActivity's `script` property carries exactly
    that basename.
    """
    resource = str((node.get("config") or {}).get("resource") or "").strip()
    if not resource:
        raise ValueError(
            f"script.groovy node '{node.get('id')}' requires config.resource "
            "(project-relative path to the .groovy source)"
        )
    if project_root is None:
        raise ValueError(
            f"script.groovy node '{node.get('id')}' requires project_root to "
            "resolve config.resource — refusing to emit a Script step whose "
            "resource would be missing from the bundle"
        )
    src = (project_root / resource).resolve()
    if not src.is_file():
        raise ValueError(f"script source not found: {src}")
    return src.name


def collect_flow_scripts(flow: dict, project_root: Path | None) -> dict[str, str]:
    """Return {bundle_path: text} for every script.groovy in the flow."""
    out: dict[str, str] = {}
    for node in flow.get("spec", {}).get("nodes", []):
        if not str(node.get("type", "")).startswith("script.groovy"):
            continue
        name = _resolve_script_name(node, project_root)
        src = (project_root / str(node["config"]["resource"])).resolve()  # type: ignore[union-attr]
        out[f"src/main/resources/script/{name}"] = src.read_text(encoding="utf-8")
    return out


def export_flow_to_iflw(
    flow: dict,
    display_name: str | None = None,
    project_root: Path | None = None,
) -> str:
    """Export one OIW IntegrationFlow dict to designer-safe .iflw text.

    `project_root` is required when the flow contains script.groovy nodes:
    each node's config.resource is resolved against it to determine the
    bundle-relative script file name.
    """
    spec = flow["spec"]
    flow_id = flow.get("metadata", {}).get("id", "flow")
    name = display_name or flow_id
    entrypoints = spec.get("entrypoints", [])
    nodes = spec.get("nodes", [])
    if len(entrypoints) != 1:
        raise ValueError(f"exporter supports exactly one entrypoint, found {len(entrypoints)}")
    entry = entrypoints[0]

    L: list[str] = []
    L.append('<?xml version="1.0" encoding="UTF-8"?>')
    L.append(
        '<bpmn2:definitions xmlns:bpmn2="http://www.omg.org/spec/BPMN/20100524/MODEL" '
        'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
        'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
        'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
        'xmlns:ifl="http:///com.sap.ifl.model/Ifl.xsd" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" id="Definitions_1">'
    )
    # Collaboration
    L.append('    <bpmn2:collaboration id="Collaboration_1" name="Default Collaboration">')
    L.append(_props(_COLLAB_PROPS))
    L.append('        <bpmn2:participant id="Participant_1" ifl:type="EndpointSender" name="Sender">')
    L.append(
        _props(
            [("enableBasicAuthentication", "false"), ("ifl:type", "EndpointSender")], indent="            "
        )
    )
    L.append("        </bpmn2:participant>")
    receivers = [n for n in nodes if n["type"].startswith("receiver.")]
    # Receiver messageFlows live in the COLLABORATION next to the sender's
    # (fixture convention), referencing the process-scoped ServiceTask ids.
    receiver_mfs: list[str] = []
    for r in receivers:
        L.append(
            f'        <bpmn2:participant id="Participant_{escape(r["id"])}" ifl:type="EndpointRecevier" name="{escape(r["id"])}">'
        )
        L.append(_props([("ifl:type", "EndpointRecevier")], indent="            "))
        L.append("        </bpmn2:participant>")
        cfg_r = r.get("config") or {}
        step_idx = nodes.index(r) + 1
        is_terminal = step_idx == len(nodes)
        if not is_terminal and r["type"] != "receiver.http":
            raise ValueError(
                f"mid-flow '{r['type']}' has no request-reply rendering — only "
                "receiver.http continues the flow with a response"
            )
        mf_source = "EndEvent_1" if is_terminal else f"ServiceTask_{step_idx}"
        if r["type"] == "receiver.processdirect":
            address = str(cfg_r.get("address", "")).strip()
            if not address:
                raise ValueError(
                    f"receiver.processdirect node '{r['id']}' requires config.address "
                    "(target process name, e.g. /oiw_pd)"
                )
            receiver_mfs.append(
                f'        <bpmn2:messageFlow id="MessageFlow_R{step_idx}" name="ProcessDirect" '
                f'sourceRef="{mf_source}" targetRef="Participant_{escape(r["id"])}">\n'
                + _props(_fill(_PROCESSDIRECT_RECEIVER_PROPS, address=escape(address)))
                + "\n        </bpmn2:messageFlow>"
            )
            continue
        if r["type"] == "receiver.sftp":
            # Password auth: the SFTP username+password live in tenant
            # security material referenced by credentialName (Security
            # Content API). The flow only names the material.
            cred = str(cfg_r.get("credentialName", "")).strip()
            if not cred:
                raise ValueError(
                    f"receiver.sftp node '{r['id']}' requires config.credentialName "
                    "— deploy User Credentials via the Security Content API and "
                    "reference them here"
                )
            host = str(cfg_r.get("host", "")).strip()
            if not host:
                raise ValueError(f"receiver.sftp node '{r['id']}' requires config.host")
            port = int(cfg_r.get("port", 22))
            directory = str(cfg_r.get("directory", "/"))
            receiver_mfs.append(
                f'        <bpmn2:messageFlow id="MessageFlow_R{step_idx}" name="SFTP" '
                f'sourceRef="{mf_source}" targetRef="Participant_{escape(r["id"])}">\n'
                + _props(
                    _fill(
                        _SFTP_RECEIVER_PROPS,
                        filename=escape(str(cfg_r.get("filename", "${date:now:yyyyMMddHHmmss}.dat"))),
                        autocreate="1" if cfg_r.get("autoCreate", True) else "0",
                        directory=escape(directory),
                        hostport=escape(f"{host}:{port}"),
                        credentialname=escape(cred),
                        sftpsec="1" if cfg_r.get("verifyHostKey", True) else "0",
                        proxytype=str(cfg_r.get("proxyType", "none")),
                        proxyport=str(cfg_r.get("proxyPort", "")),
                        proxyprotocol=str(cfg_r.get("proxyProtocol", "")),
                        proxyhost=str(cfg_r.get("proxyHost", "")),
                        locationid=str(cfg_r.get("locationId", "")),
                    )
                )
                + "\n        </bpmn2:messageFlow>"
            )
            continue
        # CPI runtime-start REQUIRES the receiver address split: the bare
        # URL in httpAddressWithoutQuery and any query string in
        # httpAddressQuery. A literal '?query' folded into WithoutQuery
        # fails runtime start (live-bisected 2026-08-26,
        # p5-p6-plan.md §6). Externalized {{params}} are NOT required.
        from urllib.parse import urlsplit

        parts = urlsplit(str(cfg_r.get("url", "")))
        url_base = f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.scheme else parts.geturl()
        url_query = parts.query
        receiver_mfs.append(
            f'        <bpmn2:messageFlow id="MessageFlow_R{step_idx}" name="HTTP" '
            f'sourceRef="{mf_source}" targetRef="Participant_{escape(r["id"])}">\n'
            + _props(
                _fill(
                    _RECEIVER_PROPS,
                    method=str(cfg_r.get("method", "GET")),
                    timeout=str(int(cfg_r.get("timeoutSeconds", 30) * 1000)),
                    system=escape(r["id"]),
                    url=url_base,
                    query=url_query,
                )
            )
            + "\n        </bpmn2:messageFlow>"
        )
    if entry.get("type") == "sender.processdirect":
        address = str((entry.get("config") or {}).get("address", "")).strip()
        if not address:
            raise ValueError(
                "sender.processdirect entrypoint requires config.address "
                "(the process name this flow listens on, e.g. /oiw_pd_hf)"
            )
        L.append(
            '        <bpmn2:messageFlow id="MessageFlow_1" name="ProcessDirect" '
            'sourceRef="Participant_1" targetRef="StartEvent_1">'
        )
        L.append(_props(_fill(_PROCESSDIRECT_SENDER_PROPS, address=escape(address))))
        L.append("        </bpmn2:messageFlow>")
    else:
        path = str((entry.get("config") or {}).get("path", "/"))
        L.append(
            '        <bpmn2:messageFlow id="MessageFlow_1" name="HTTPS" sourceRef="Participant_1" targetRef="StartEvent_1">'
        )
        L.append(_props(_fill(_SENDER_PROPS, path=path, system=escape(name))))
        L.append("        </bpmn2:messageFlow>")
    # Every real export declares the process as an IntegrationProcess
    # participant with processRef (runtime binds endpoint routing to it).
    L.append(
        '<bpmn2:participant id="Participant_Process_1" ifl:type="IntegrationProcess" '
        'name="Integration Process" processRef="Process_1">'
        "<bpmn2:extensionElements/></bpmn2:participant>"
    )
    for mf in receiver_mfs:
        L.append(mf)
    L.append("    </bpmn2:collaboration>")
    L.append('    <bpmn2:process id="Process_1" name="Integration Process">')
    L.append(
        _props(
            [
                ("transactionTimeout", "30"),
                ("componentVersion", "1.1"),
                ("cmdVariantUri", "ctype::FlowElementVariant/cname::IntegrationProcess/version::1.1.3"),
                ("transactionalHandling", "Required"),
            ]
        )
    )
    L.append('        <bpmn2:startEvent id="StartEvent_1" name="Start">')
    L.append(
        _props(
            [
                ("componentVersion", "1.0"),
                ("cmdVariantUri", "ctype::FlowstepVariant/cname::MessageStartEvent/version::1.0"),
            ],
            indent="            ",
        )
    )
    L.append("            <bpmn2:outgoing>SequenceFlow_0</bpmn2:outgoing>")
    L.append("            <bpmn2:messageEventDefinition/>")
    L.append("        </bpmn2:startEvent>")

    # CPI compiled model (from UI-authored reference exports):
    #  - TERMINAL receivers render as EndEvent + messageFlow(EndEvent ->
    #    participant) — HTTP and ProcessDirect both proven live.
    #  - MID-FLOW receiver.http renders as Request-Reply:
    #    serviceTask(activityType=ExternalCall) whose messageFlow carries
    #    the HTTP adapter props; the RESPONSE continues in the main flow
    #    (reference: testing_oiw v3, ServiceTask_6 "Request Reply 1").
    receiver_terminals: set[int] = set()
    for i, node in enumerate(nodes, start=1):
        if node["type"].startswith("receiver.") and i == len(nodes):
            receiver_terminals.add(i)

    for i, node in enumerate(nodes, start=1):
        nid = _elem_id(node["type"], i)
        ntype = node["type"]
        cfg = node.get("config") or {}
        incoming = f"SequenceFlow_{i - 1}"
        outgoing = f"SequenceFlow_{i}"
        if i in receiver_terminals:
            continue  # rendered as EndEvent below
        if ntype.startswith("receiver."):
            if ntype != "receiver.http":
                raise ValueError(
                    f"mid-flow '{ntype}' has no request-reply rendering — only "
                    "receiver.http continues the flow with a response"
                )
            # Request-Reply: response data flows on to the next step.
            L.append(f'        <bpmn2:serviceTask id="{nid}" name="{escape(str(node["id"]))}">')
            L.append(
                _props(
                    [
                        ("activityType", "ExternalCall"),
                        (
                            "cmdVariantUri",
                            "ctype::FlowstepVariant/cname::ExternalCall/version::1.0.4",
                        ),
                    ],
                    indent="            ",
                )
            )
            L.append(f"            <bpmn2:incoming>{incoming}</bpmn2:incoming>")
            L.append(f"            <bpmn2:outgoing>{outgoing}</bpmn2:outgoing>")
            L.append("        </bpmn2:serviceTask>")
            continue
        else:
            activity = _OIW_TO_ACTIVITY.get(ntype)
            if activity is None:
                raise ValueError(
                    f"no designer-proven CPI mapping for OIW node type '{ntype}' — "
                    "refusing to emit a bundle that would break the web designer"
                )
            extra: list[tuple[str, str]]
            if activity == "Enricher":
                msg = str(cfg.get("message", "")) if ntype == "log.message" else ""
                extra = [
                    ("bodyType", "constant" if ntype == "log.message" else "expression"),
                    ("propertyTable", ""),
                    ("headerTable", ""),
                    ("wrapContent", msg),
                    ("componentVersion", "1.5"),
                    ("activityType", "Enricher"),
                    ("cmdVariantUri", "ctype::FlowstepVariant/cname::Enricher/version::1.5.1"),
                ]
            elif activity == "JsonToXmlConverter":
                extra = [
                    ("additionalRootElementName", "root"),
                    ("jsonNamespaceMapping", ""),
                    ("useNamespaces", "true"),
                    ("addXMLRootElement", "true"),
                    ("additionalRootElementNamespace", ""),
                    ("jsonNamespaceSeparator", ":"),
                    ("componentVersion", "1.1"),
                    ("activityType", "JsonToXmlConverter"),
                    ("cmdVariantUri", "ctype::FlowstepVariant/cname::JsonToXmlConverter/version::1.1.1"),
                ]
            elif activity == "Script":
                resource = _resolve_script_name(node, project_root)
                extra = [
                    ("scriptFunction", str(cfg.get("function", "processData"))),
                    ("scriptBundleId", ""),
                    ("componentVersion", "1.1"),
                    ("activityType", "Script"),
                    ("cmdVariantUri", "ctype::FlowstepVariant/cname::GroovyScript/version::1.1.1"),
                    ("subActivityType", "GroovyScript"),
                    ("script", escape(resource)),
                ]
            elif activity == "Variables":
                # Mirrored from UI-authored reference (oiw_pd, "Write
                # Variables 1"): the variable property is a row-XML cell
                # table: [name, '', type, value, scope].
                name_v = escape(str(cfg.get("name", "")))
                if not name_v:
                    raise ValueError(f"variables.write node '{node['id']}' requires config.name")
                # Operator-corrected expression (2026-08-26): ${body},
                # not the $in.body seen in the first reference export.
                value = escape(str(cfg.get("value", "${body}")))
                vtype = escape(str(cfg.get("valueType", "expression")))
                scope = escape(str(cfg.get("scope", "global")))
                row = f"<row><cell>{name_v}</cell><cell></cell><cell>{vtype}</cell><cell>{value}</cell><cell>{scope}</cell></row>"
                extra = [
                    ("visibility", str(cfg.get("visibility", "local"))),
                    ("encrypt", str(cfg.get("encrypt", "false")).lower()),
                    ("expire", str(cfg.get("expire", "90"))),
                    ("variable", row),
                    ("activityType", "Variables"),
                    (
                        "cmdVariantUri",
                        "ctype::FlowstepVariant/cname::Variables/version::1.2.0",
                    ),
                ]
            else:
                raise ValueError(f"unhandled activity {activity}")
            L.append(f'        <bpmn2:callActivity id="{nid}" name="{escape(str(node["id"]))}">')
            L.append(_props(extra, indent="            "))
            L.append(f"            <bpmn2:incoming>{incoming}</bpmn2:incoming>")
            L.append(f"            <bpmn2:outgoing>{outgoing}</bpmn2:outgoing>")
            L.append("        </bpmn2:callActivity>")

    L.append('        <bpmn2:endEvent id="EndEvent_1" name="End">')
    L.append(
        _props(
            [
                ("componentVersion", "1.1"),
                ("cmdVariantUri", "ctype::FlowstepVariant/cname::MessageEndEvent/version::1.1.0"),
            ],
            indent="            ",
        )
    )
    L.append(f"            <bpmn2:incoming>SequenceFlow_{len(nodes)}</bpmn2:incoming>")
    L.append("            <bpmn2:messageEventDefinition/>")
    L.append("        </bpmn2:endEvent>")

    # All sequenceFlows declared at process end, mirroring real exports.
    # Terminal receivers collapse into EndEvent_1 (their messageFlow wires
    # EndEvent_1 -> Participant_x in the collaboration).
    ids = (
        ["StartEvent_1"]
        + [_elem_id(n["type"], i) for i, n in enumerate(nodes, start=1) if i not in receiver_terminals]
        + ["EndEvent_1"]
    )
    for i in range(len(ids) - 1):
        L.append(
            f'        <bpmn2:sequenceFlow id="SequenceFlow_{i}" sourceRef="{ids[i]}" targetRef="{ids[i + 1]}"/>'
        )
    L.append("    </bpmn2:process>")
    L.append(_diagram_section(flow, nodes, receiver_terminals, name))
    L.append("</bpmn2:definitions>")
    return "\n".join(L)


def _diagram_section(flow: dict, nodes: list[dict], receiver_terminals: set[int], flow_name: str) -> str:
    """bpmndi section — REQUIRED for the web designer to open the artifact.

    Bundles without BPMNDiagram deploy and run but render unopenable in
    the UI (live finding, 2026-08-26). Layout mirrors the coordinate
    scheme of real UI exports: sender left, process lane center with
    steps left-to-right, HTTP receivers above their Request-Reply tasks,
    terminal receivers right of the end event.
    """
    entry_id = "StartEvent_1"
    shapes: list[tuple[str, int, int, int, int]] = []  # id,x,y,w,h

    # Process-lane geometry
    step_x0, step_y, task_w, task_h = 412, 132, 100, 60
    rendered = [i for i in range(1, len(nodes) + 1) if i not in receiver_terminals]
    last_right = step_x0 - 150 + 150 * len(rendered) + task_w if rendered else 292 + 32
    end_x = last_right + 41 if rendered else 365

    shapes.append((entry_id, 292, 142, 32, 32))
    k = 0
    for i, node in enumerate(nodes, start=1):
        if i in receiver_terminals:
            continue
        x = step_x0 + 150 * k
        shapes.append((_elem_id(node["type"], i), x, step_y, task_w, task_h))
        k += 1
    shapes.append(("EndEvent_1", end_x, 142, 32, 32))
    shapes.append(("Participant_1", 40, 100, 100, 140))  # sender
    shapes.append(("Participant_Process_1", 250, 60, end_x + 87 - 250, 220))

    # Receiver participants: mid-flow (Request-Reply) above their task;
    # terminal receivers right of the end event.
    k = 0
    for i, node in enumerate(nodes, start=1):
        if not node["type"].startswith("receiver."):
            continue
        pid = f"Participant_{node['id']}"
        if i in receiver_terminals:
            shapes.append((pid, end_x + 175, 69, 100, 140))
        else:
            shapes.append((pid, step_x0 + 150 * k + 8, -182, 100, 140))
            k += 1

    def center(shape_id: str) -> tuple[int, int]:
        _, x, y, w, h = next(s for s in shapes if s[0] == shape_id)
        return x + w // 2, y + h // 2

    edges: list[tuple[str, str, str]] = []  # bpmnId, sourceShapeId, targetShapeId
    seq_ids = (
        ["StartEvent_1"]
        + [_elem_id(n["type"], i) for i, n in enumerate(nodes, start=1) if i not in receiver_terminals]
        + ["EndEvent_1"]
    )
    for i in range(len(seq_ids) - 1):
        edges.append((f"SequenceFlow_{i}", seq_ids[i], seq_ids[i + 1]))
    edges.append(("MessageFlow_1", "Participant_1", "StartEvent_1"))
    for r in nodes:
        if not r["type"].startswith("receiver."):
            continue
        idx = nodes.index(r) + 1
        src = "EndEvent_1" if idx == len(nodes) else f"ServiceTask_{idx}"
        edges.append((f"MessageFlow_R{idx}", src, f"Participant_{r['id']}"))

    out = ['    <bpmndi:BPMNDiagram id="BPMNDiagram_1" name="Default Collaboration Diagram">']
    out.append('        <bpmndi:BPMNPlane bpmnElement="Collaboration_1" id="BPMNPlane_1">')
    for sid, x, y, w, h in shapes:
        out.append(f'            <bpmndi:BPMNShape bpmnElement="{escape(sid)}" id="BPMNShape_{escape(sid)}">')
        out.append(
            f'                <dc:Bounds height="{float(h)}" width="{float(w)}" x="{float(x)}" y="{float(y)}"/>'
        )
        out.append("            </bpmndi:BPMNShape>")
    for eid, src, tgt in edges:
        sx, sy = center(src)
        tx, ty = center(tgt)
        out.append(
            f'            <bpmndi:BPMNEdge bpmnElement="{escape(eid)}" id="BPMNEdge_{escape(eid)}" '
            f'sourceElement="BPMNShape_{escape(src)}" targetElement="BPMNShape_{escape(tgt)}">'
        )
        out.append(f'                <di:waypoint x="{float(sx)}" xsi:type="dc:Point" y="{float(sy)}"/>')
        out.append(f'                <di:waypoint x="{float(tx)}" xsi:type="dc:Point" y="{float(ty)}"/>')
        out.append("            </bpmndi:BPMNEdge>")
    out.append("        </bpmndi:BPMNPlane>")
    out.append("    </bpmndi:BPMNDiagram>")
    return "\n".join(out)


def _fold_manifest_line(line: str, limit: int = 70) -> str:
    """Fold one manifest header to jar-spec continuation lines.

    JAR manifests reject lines >72 bytes; continuations start with a
    single space. Splits after commas first (OSGi header convention).
    """
    key, sep, val = line.partition(": ")
    if not sep:
        return line
    out: list[str] = []
    cur = f"{key}: "
    for i, part in enumerate(val.split(",")):
        piece = part if i == 0 else "," + part
        if len(cur) + len(piece) > limit and cur.strip():
            out.append(cur.rstrip())
            cur = " " + part.lstrip()
        else:
            cur += piece
    out.append(cur.rstrip())
    return "\n".join(out)


_MANIFEST_TEMPLATE = """Manifest-Version: 1.0
Bundle-ManifestVersion: 2
Bundle-Name: {name}
Bundle-SymbolicName: {symbolic};singleton:=true
Bundle-Version: 1.0.0
SAP-BundleType: IntegrationFlow
SAP-NodeType: IFLMAP
SAP-RuntimeProfile: iflmap
"""


def cpi_bundle_identity(existing_zip: bytes) -> tuple[str, str, str]:
    """Extract (Bundle-SymbolicName, iflw filename, Bundle-Name) from a bundle."""
    with zipfile.ZipFile(BytesIO(existing_zip)) as zf:
        names = zf.namelist()
        symbolic = bundle_name = None
        for n in names:
            if n.endswith("MANIFEST.MF"):
                for line in zf.read(n).decode("utf-8", "replace").splitlines():
                    if line.startswith("Bundle-SymbolicName:"):
                        symbolic = line.split(":", 1)[1].strip().split(";")[0]
                    elif line.startswith("Bundle-Name:"):
                        bundle_name = line.split(":", 1)[1].strip()
            if symbolic and bundle_name:
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
        raise ValueError("existing bundle lacks MANIFEST.MF SymbolicName or an .iflw entry")
    return symbolic, iflw, bundle_name or symbolic


def build_cpi_bundle(
    flow: dict,
    symbolic_name: str | None = None,
    iflw_name: str | None = None,
    display_name: str | None = None,
    import_headers: str | None = None,
    project_root: Path | None = None,
) -> tuple[bytes, str]:
    """Build the designtime ZIP for one flow. Returns (bytes, sha256hex).

    `import_headers`: optional raw text of extra OSGi manifest headers
    (e.g. "Import-Package: ...\nImport-Service: ...") — folded to the
    72-byte jar limit automatically.

    `project_root`: required when the flow contains script.groovy nodes;
    their sources are emitted under src/main/resources/script/.
    """
    flow_id = flow.get("metadata", {}).get("id", "flow")
    name = display_name or flow_id
    symbolic = symbolic_name or flow_id.replace("-", "_").replace(".", "_")
    iflw_file = Path(iflw_name or f"{flow_id}.iflw").name
    iflw = export_flow_to_iflw(flow, display_name=name, project_root=project_root)
    scripts = collect_flow_scripts(flow, project_root)

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
            "META-INF/MANIFEST.MF": "\n".join(
                [
                    _fold_manifest_line(line)
                    for line in _MANIFEST_TEMPLATE.format(
                        symbolic=escape(symbolic), name=escape(name)
                    ).splitlines()
                ]
                + [_fold_manifest_line(line) for line in (import_headers or "").splitlines() if line.strip()]
            )
            + "\n",
            "metainfo.prop": "",
            f"src/main/resources/scenarioflows/integrationflow/{iflw_file}": iflw,
        }
        entries.update(scripts)
        for ename in sorted(entries):
            info = zipfile.ZipInfo(ename, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, entries[ename])
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()


__all__ = [
    "build_cpi_bundle",
    "cpi_bundle_identity",
    "collect_flow_scripts",
    "export_flow_to_iflw",
]
