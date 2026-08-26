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

# SFTP sender (polling fetch) messageFlow — mirrored verbatim from a live
# UI-authored poller (DPWORLD_SFTP_QAS). Delete-on-fetch semantics: no
# file.move / doneFileName keys => Camel deletes the file after successful
# routing. Cron polls every minute.
_SFTP_POLL_CRON_MINUTE = (
    "<row><cell>dayValue</cell><cell></cell></row>"
    "<row><cell>monthValue</cell><cell></cell></row>"
    "<row><cell>yearValue</cell><cell></cell></row>"
    "<row><cell>dateType</cell><cell>DAILY</cell></row>"
    "<row><cell>secondValue</cell><cell>0</cell></row>"
    "<row><cell>minutesValue</cell><cell></cell></row>"
    "<row><cell>hourValue</cell><cell></cell></row>"
    "<row><cell>toInterval</cell><cell>24</cell></row>"
    "<row><cell>fromInterval</cell><cell>0</cell></row>"
    "<row><cell>OnEveryMinute</cell><cell>1</cell></row>"
    "<row><cell>timeType</cell><cell>TIME_INTERVAL</cell></row>"
    "<row><cell>timeZone</cell><cell>( UTC 5:30 ) India Standard Time(Asia/Kolkata)</cell></row>"
    "<row><cell>throwExceptionOnExpiry</cell><cell>true</cell></row>"
    "<row><cell>second</cell><cell>0/10</cell></row>"
    "<row><cell>minute</cell><cell>*</cell></row>"
    "<row><cell>hour</cell><cell>0-24</cell></row>"
    "<row><cell>day_of_month</cell><cell>?</cell></row>"
    "<row><cell>month</cell><cell>*</cell></row>"
    "<row><cell>dayOfWeek</cell><cell>*</cell></row>"
    "<row><cell>year</cell><cell>*</cell></row>"
    "<row><cell>startAt</cell><cell></cell></row>"
    "<row><cell>endAt</cell><cell></cell></row>"
    "<row><cell>attributeBehaviour</cell><cell>isScheduleOnDayRequired,isScheduleRecurRequired,isScheduleAdvancedVisible</cell></row>"
    "<row><cell>triggerType</cell><cell>cron</cell></row>"
    "<row><cell>noOfSchedules</cell><cell>1</cell></row>"
    "<row><cell>schedule1</cell><cell>0+0/1+0-23+?+*+*+*&amp;trigger.timeZone=Asia/Kolkata</cell></row>"
)

_SFTP_SENDER_PROPS = [
    ("disconnect", "1"),
    ("fileName", "{filename}"),
    ("maximumFileSize", "40"),
    ("privateKeyAlias", ""),
    ("emptyFileHandling", "skipFile"),
    ("location_id", "{locationid}"),
    ("Name", "SFTP"),
    ("TransportProtocolVersion", "1.20.1"),
    ("flatten", "0"),
    ("proxyPort", "{proxyport}"),
    ("path", "{directory}"),
    ("useClusterLock", "0"),
    ("regex_filter", "0"),
    ("host", "{hostport}"),
    ("connectTimeout", "10000"),
    ("file_sorting_criteria", "sort_by_none"),
    ("maxMessagesPerPoll", "20"),
    ("fastExistsCheck", "1"),
    ("ComponentSWCVId", "1.20.1"),
    ("credential_name", "{credentialname}"),
    ("readLock", "none"),
    ("componentVersion", "1.20"),
    ("proxyHost", "{proxyhost}"),
    ("system", "DPWorld"),
    ("stopOnException", "1"),
    ("scheduleKey", "{schedule}"),
    ("allowDeprecatedAlgorithms", "0"),
    ("TransportProtocol", "SFTP"),
    (
        "cmdVariantUri",
        "ctype::AdapterVariant/cname::sap:SFTP/tp::SFTP/mp::File/direction::Sender/version::1.20.1",
    ),
    ("MessageProtocolVersion", "1.20.1"),
    ("file_lock_timeout", "15"),
    ("Description", ""),
    ("readLockCheckInterval", "5000"),
    ("maximumReconnectAttempts", "3"),
    ("stepwise", "0"),
    ("ComponentNS", "sap"),
    ("recursive", "0"),
    ("ComponentSWCVName", "external"),
    ("noop", "delete"),
    ("doneFileName", "${{file:name}}.done"),
    ("file.move", ".archive"),
    ("MessageProtocol", "File"),
    ("direction", "Sender"),
    ("authentication", "user_password"),
    ("file_sorting_direction", "sort_direction_asc"),
    ("ComponentType", "SFTP"),
    ("proxyProtocol", "{proxyprotocol}"),
    ("idempotentRepository", "database"),
    ("proxyType", "{proxytype}"),
    ("proxyAlias", ""),
    ("reconnectDelay", "1000"),
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


def _branch_chains(spec: dict) -> tuple[list[dict], dict[str, int]]:
    """Split nodes into one linear branch per entrypoint (BFS via edges).

    Returns (branches, gid) where each branch = {"entry": entrypoint,
    "nodes": [node dicts]} and gid maps node-id -> global 1-based index
    used for BPMN element ids.
    """
    adjacency: dict[str, list[str]] = {}
    for e in spec.get("edges", []) or []:
        adjacency.setdefault(e["from"], []).append(e["to"])

    nodes_by_id = {n["id"]: n for n in spec.get("nodes", [])}
    branches: list[dict] = []
    claimed: set[str] = set()
    for ep in spec.get("entrypoints", []):
        chain: list[dict] = []
        cur = ep["id"]
        while True:
            node = nodes_by_id.get(cur)
            if node is not None and cur not in claimed:
                claimed.add(cur)
                chain.append(node)
            nxt = adjacency.get(cur, [])
            if not nxt or nxt[0] in claimed:
                break
            cur = nxt[0]
        branches.append({"entry": ep, "nodes": chain})
        # guard against infinite loops on cyclic specs
        if len(claimed) > len(nodes_by_id) + 1:
            break

    # Orphan nodes (unreachable via edges) keep legacy linear placement:
    # append to the first branch in spec order.
    for n in spec.get("nodes", []):
        if n["id"] not in claimed:
            branches[0]["nodes"].append(n)
            claimed.add(n["id"])

    gid: dict[str, int] = {}
    g = 0
    for b in branches:
        for n in b["nodes"]:
            g += 1
            gid[n["id"]] = g
    return branches, gid


def export_flow_to_iflw(
    flow: dict,
    display_name: str | None = None,
    project_root: Path | None = None,
) -> str:
    """Export one OIW IntegrationFlow dict to designer-safe .iflw text.

    Multi-entrypoint aware: every entrypoint owns one linear branch
    (HTTPS writer + SFTP poller can coexist in ONE artifact — proven
    pattern from DPWORLD_SFTP_QAS reference). `project_root` is required
    when the flow contains script.groovy nodes.
    """
    spec = flow["spec"]
    flow_id = flow.get("metadata", {}).get("id", "flow")
    name = display_name or flow_id
    branches, gid = _branch_chains(spec)
    if not branches:
        raise ValueError("flow requires at least one entrypoint")

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
    L.append('    <bpmn2:collaboration id="Collaboration_1" name="Default Collaboration">')
    L.append(_props(_COLLAB_PROPS))

    # --- sender participants (one per entrypoint) ---
    for bi, b in enumerate(branches, start=1):
        pid = "Participant_1" if bi == 1 else f"Participant_E{bi}"
        L.append(
            f'        <bpmn2:participant id="{pid}" ifl:type="EndpointSender" name="Sender">'
        )
        L.append(
            _props(
                [("enableBasicAuthentication", "false"), ("ifl:type", "EndpointSender")],
                indent="            ",
            )
        )
        L.append("        </bpmn2:participant>")

    # --- receiver participants + their messageFlows ---
    receiver_mfs: list[str] = []
    seen_receiver_participants: set[str] = set()

    def _receiver_participant(r: dict) -> None:
        rid = f'Participant_{escape(r["id"])}'
        if rid in seen_receiver_participants:
            return
        seen_receiver_participants.add(rid)
        L.append(
            f'        <bpmn2:participant id="{rid}" ifl:type="EndpointRecevier" ' f'name="{escape(r["id"])}">'
        )
        L.append(_props([("ifl:type", "EndpointRecevier")], indent="            "))
        L.append("        </bpmn2:participant>")

    def _receiver_mf(r: dict, bi: int) -> None:
        """Emit receiver participant + messageFlow for one receiver node."""
        _receiver_participant(r)
        cfg_r = r.get("config") or {}
        gid_i = gid[r["id"]]
        chain = b_nodes[bi]
        is_terminal = chain and r["id"] == chain[-1]["id"]
        if not is_terminal and r["type"] != "receiver.http":
            raise ValueError(
                f"mid-flow '{r['type']}' has no request-reply rendering — only "
                "receiver.http continues the flow with a response"
            )
        mf_source = f"EndEvent_{bi}" if is_terminal else f"ServiceTask_{gid_i}"
        mf_id = f"MessageFlow_R{gid_i}"
        if r["type"] == "receiver.processdirect":
            address = str(cfg_r.get("address", "")).strip()
            if not address:
                raise ValueError(
                    f"receiver.processdirect node '{r['id']}' requires config.address "
                    "(target process name, e.g. /oiw_pd)"
                )
            receiver_mfs.append(
                f'        <bpmn2:messageFlow id="{mf_id}" name="ProcessDirect" '
                f'sourceRef="{mf_source}" targetRef="Participant_{escape(r["id"])}">\n'
                + _props(_fill(_PROCESSDIRECT_RECEIVER_PROPS, address=escape(address)))
                + "\n        </bpmn2:messageFlow>"
            )
        elif r["type"] == "receiver.sftp":
            cred = str(cfg_r.get("credentialName", "")).strip()
            if not cred:
                raise ValueError(
                    f"receiver.sftp node '{r['id']}' requires config.credentialName "
                    "— deploy User Credentials via the Security Content API"
                )
            host = str(cfg_r.get("host", "")).strip()
            if not host:
                raise ValueError(f"receiver.sftp node '{r['id']}' requires config.host")
            port = int(cfg_r.get("port", 22))
            directory = str(cfg_r.get("directory", "/"))
            receiver_mfs.append(
                f'        <bpmn2:messageFlow id="{mf_id}" name="SFTP" '
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
        else:
            # HTTP — runtime-start REQUIRES the URL split (live-bisected);
            # externalized {{params}} NOT required.
            from urllib.parse import urlsplit

            parts = urlsplit(str(cfg_r.get("url", "")))
            url_base = f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.scheme else parts.geturl()
            receiver_mfs.append(
                f'        <bpmn2:messageFlow id="{mf_id}" name="HTTP" '
                f'sourceRef="{mf_source}" targetRef="Participant_{escape(r["id"])}">\n'
                + _props(
                    _fill(
                        _RECEIVER_PROPS,
                        method=str(cfg_r.get("method", "GET")),
                        timeout=str(int(cfg_r.get("timeoutSeconds", 30) * 1000)),
                        system=escape(r["id"]),
                        url=url_base,
                        query=parts.query,
                    )
                )
                + "\n        </bpmn2:messageFlow>"
            )

    b_nodes: dict[int, list[dict]] = {bi: b["nodes"] for bi, b in enumerate(branches, start=1)}
    for bi, b in enumerate(branches, start=1):
        for n in b["nodes"]:
            if n["type"].startswith("receiver."):
                _receiver_mf(n, bi)

    # --- sender messageFlows (one per entrypoint) ---
    for bi, b in enumerate(branches, start=1):
        ep = b["entry"]
        pid = "Participant_1" if bi == 1 else f"Participant_E{bi}"
        target = f"StartEvent_{bi}"
        etype = ep.get("type", "sender.http")
        cfg_e = ep.get("config") or {}
        mf_id = "MessageFlow_1" if bi == 1 else f"MessageFlow_S{bi}"
        if etype == "sender.processdirect":
            address = str(cfg_e.get("address", "")).strip()
            if not address:
                raise ValueError(
                    "sender.processdirect entrypoint requires config.address "
                    "(the process name this flow listens on)"
                )
            L.append(
                f'        <bpmn2:messageFlow id="{mf_id}" name="ProcessDirect" '
                f'sourceRef="{pid}" targetRef="{target}">'
            )
            L.append(_props(_fill(_PROCESSDIRECT_SENDER_PROPS, address=escape(address))))
            L.append("        </bpmn2:messageFlow>")
        elif etype == "sender.sftp":
            cred = str(cfg_e.get("credentialName", "")).strip()
            host = str(cfg_e.get("host", "")).strip()
            if not cred or not host:
                raise ValueError(
                    "sender.sftp entrypoint requires config.host and "
                    "config.credentialName (polling fetch + delete-on-success)"
                )
            port = int(cfg_e.get("port", 22))
            L.append(
                f'        <bpmn2:messageFlow id="{mf_id}" name="SFTP" '
                f'sourceRef="{pid}" targetRef="{target}">'
            )
            L.append(
                _props(
                    _fill(
                        _SFTP_SENDER_PROPS,
                        filename=escape(str(cfg_e.get("filenameFilter", ".*"))),
                        directory=escape(str(cfg_e.get("directory", "/"))),
                        hostport=escape(f"{host}:{port}"),
                        credentialname=escape(cred),
                        schedule=_SFTP_POLL_CRON_MINUTE,
                        proxytype=str(cfg_e.get("proxyType", "none")),
                        proxyport=str(cfg_e.get("proxyPort", "")),
                        proxyprotocol=str(cfg_e.get("proxyProtocol", "")),
                        proxyhost=str(cfg_e.get("proxyHost", "")),
                        locationid=str(cfg_e.get("locationId", "")),
                        system="Sender",
                    )
                )
            )
            L.append("        </bpmn2:messageFlow>")
        else:
            path = str(cfg_e.get("path", "/"))
            L.append(
                f'        <bpmn2:messageFlow id="{mf_id}" name="HTTPS" '
                f'sourceRef="{pid}" targetRef="{target}">'
            )
            L.append(_props(_fill(_SENDER_PROPS, path=path, system=escape(name))))
            L.append("        </bpmn2:messageFlow>")

    L.append(
        '<bpmn2:participant id="Participant_Process_1" ifl:type="IntegrationProcess" '
        'name="Integration Process" processRef="Process_1">'
        "<bpmn2:extensionElements/></bpmn2:participant>"
    )
    for mf in receiver_mfs:
        L.append(mf)
    L.append("    </bpmn2:collaboration>")

    # ---------------- process: one branch per entrypoint -----------------
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

    seq_counter = 0
    for bi, b in enumerate(branches, start=1):
        chain = b["nodes"]
        start_id = f"StartEvent_{bi}"
        L.append(f'        <bpmn2:startEvent id="{start_id}" name="Start">')
        L.append(
            _props(
                [
                    ("componentVersion", "1.0"),
                    ("cmdVariantUri", "ctype::FlowstepVariant/cname::MessageStartEvent/version::1.0"),
                ],
                indent="            ",
            )
        )
        L.append(f"            <bpmn2:outgoing>SequenceFlow_{seq_counter}</bpmn2:outgoing>")
        L.append("            <bpmn2:messageEventDefinition/>")
        L.append("        </bpmn2:startEvent>")

        for li, node in enumerate(chain):
            gid_i = gid[node["id"]]
            nid = _elem_id(node["type"], gid_i)
            ntype = node["type"]
            cfg = node.get("config") or {}
            is_last = li == len(chain) - 1
            terminal_receiver = is_last and ntype.startswith("receiver.")

            if terminal_receiver:
                break  # rendered as EndEvent below

            incoming = f"SequenceFlow_{seq_counter}"
            outgoing = f"SequenceFlow_{seq_counter + 1}"
            seq_counter += 1

            if ntype.startswith("receiver."):
                if ntype != "receiver.http":
                    raise ValueError(
                        f"mid-flow '{ntype}' has no request-reply rendering — only "
                        "receiver.http continues the flow with a response"
                    )
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
                name_v = escape(str(cfg.get("name", "")))
                if not name_v:
                    raise ValueError(f"variables.write node '{node['id']}' requires config.name")
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
                    ("cmdVariantUri", "ctype::FlowstepVariant/cname::Variables/version::1.2.0"),
                ]
            else:
                raise ValueError(f"unhandled activity {activity}")

            tag = "serviceTask" if activity in ("ExternalCall",) else "callActivity"
            L.append(f'        <bpmn2:{tag} id="{nid}" name="{escape(str(node["id"]))}">')
            L.append(_props(extra, indent="            "))
            L.append(f"            <bpmn2:incoming>{incoming}</bpmn2:incoming>")
            L.append(f"            <bpmn2:outgoing>{outgoing}</bpmn2:outgoing>")
            L.append(f"        </bpmn2:{tag}>")

        # Branch end event: message-typed when the branch terminates in a
        # receiver adapter (its messageFlow hangs off this end); otherwise
        # a plain end event (no messageEventDefinition).
        end_id = f"EndEvent_{bi}"
        last = chain[-1] if chain else None
        msg_typed = bool(last and last["type"].startswith("receiver."))
        incoming = f"SequenceFlow_{seq_counter}"
        seq_counter += 1
        L.append(f'        <bpmn2:endEvent id="{end_id}" name="End">')
        # Plain vs message-typed ends differ in variant URI (CodeJam
        # fixture: cname::EndEvent for plain, MessageEndEvent/1.1.0 for
        # message-typed with <messageEventDefinition/>).
        end_props: list[tuple[str, str]] = [("componentVersion", "1.1")]
        if msg_typed:
            end_props.append(
                ("cmdVariantUri", "ctype::FlowstepVariant/cname::MessageEndEvent/version::1.1.0")
            )
            L.append(_props(end_props, indent="            "))
            L.append(f"            <bpmn2:incoming>{incoming}</bpmn2:incoming>")
            L.append("            <bpmn2:messageEventDefinition/>")
        else:
            end_props.append(("cmdVariantUri", "ctype::FlowstepVariant/cname::EndEvent"))
            L.append(_props(end_props, indent="            "))
            L.append(f"            <bpmn2:incoming>{incoming}</bpmn2:incoming>")
        L.append("        </bpmn2:endEvent>")

        # sequenceFlows for this branch (declared at process end, fixture convention)
        elem_ids = [start_id]
        for node in chain:
            if node is last and last is not None and last["type"].startswith("receiver."):
                continue
            elem_ids.append(_elem_id(node["type"], gid[node["id"]]))
        elem_ids.append(end_id)
        for i in range(len(elem_ids) - 1):
            L.append(
                f'        <bpmn2:sequenceFlow id="SequenceFlow_{seq_counter - len(elem_ids) + 1 + i}" '
                f'sourceRef="{elem_ids[i]}" targetRef="{elem_ids[i + 1]}"/>'
            )

    L.append("    </bpmn2:process>")
    L.append(_diagram_section(flow, branches, gid, name))
    L.append("</bpmn2:definitions>")
    return "\n".join(L)


def _diagram_section(flow: dict, branches: list[dict], gid: dict[str, int], flow_name: str) -> str:
    """bpmndi section — REQUIRED for the web designer to open the artifact.

    Bundles without BPMNDiagram deploy and run but render unopenable in
    the UI (live finding, 2026-08-26). Layout mirrors real UI exports;
    branches are laid out side by side (430px pitch).
    """
    shapes: list[tuple[str, int, int, int, int]] = []
    edges: list[tuple[str, str, str]] = []

    for bi, b in enumerate(branches, start=1):
        off = 430 * (bi - 1)
        chain = b["nodes"]
        step_x0, step_y, task_w, task_h = 412 + off, 132, 100, 60
        rendered = [
            n for n in chain if not (chain.index(n) == len(chain) - 1 and n["type"].startswith("receiver."))
        ]
        last_right = step_x0 - 150 + 150 * len(rendered) + task_w if rendered else (292 + off) + 32
        end_x = last_right + 41 if rendered else (292 + off) + 73

        start_id = f"StartEvent_{bi}"
        end_id = f"EndEvent_{bi}"
        sender_pid = "Participant_1" if bi == 1 else f"Participant_E{bi}"

        shapes.append((start_id, 292 + off, 142, 32, 32))
        k = 0
        for n in rendered:
            x = step_x0 + 150 * k
            shapes.append((_elem_id(n["type"], gid[n["id"]]), x, step_y, task_w, task_h))
            k += 1
        shapes.append((end_id, end_x, 142, 32, 32))
        shapes.append((sender_pid, 40 + off, 100, 100, 140))
        shapes.append(("Participant_Process_1", 250 + off, 60, end_x + 87 - (250 + off), 220))

        # receiver participants
        for n in chain:
            if not n["type"].startswith("receiver."):
                continue
            pid = f'Participant_{n["id"]}'
            gi = gid[n["id"]]
            is_terminal = n is chain[-1]
            if is_terminal:
                shapes.append((pid, end_x + 175, 69, 100, 140))
            else:
                shapes.append((pid, step_x0 + 150 * k + 8, -182, 100, 140))
                k += 1

        def center(shape_id: str) -> tuple[int, int]:
            _, x, y, w, h = next(s for s in shapes if s[0] == shape_id)
            return x + w // 2, y + h // 2

        # sequenceFlow edges
        elem_ids = [start_id]
        for n in rendered:
            elem_ids.append(_elem_id(n["type"], gid[n["id"]]))
        elem_ids.append(end_id)
        base = seq_base(flow, bi)
        for i in range(len(elem_ids) - 1):
            edges.append((f"SequenceFlow_{base + i}", elem_ids[i], elem_ids[i + 1]))

        edges.append(("MessageFlow_1" if bi == 1 else f"MessageFlow_S{bi}", sender_pid, start_id))
        for n in chain:
            if not n["type"].startswith("receiver."):
                continue
            gi = gid[n["id"]]
            src = end_id if n is chain[-1] else f"ServiceTask_{gi}"
            edges.append((f"MessageFlow_R{gi}", src, f'Participant_{n["id"]}'))

    out = ['    <bpmndi:BPMNDiagram id="BPMNDiagram_1" name="Default Collaboration Diagram">']
    out.append('        <bpmndi:BPMNPlane bpmnElement="Collaboration_1" id="BPMNPlane_1">')
    for sid, x, y, w, h in shapes:
        out.append(f'            <bpmndi:BPMNShape bpmnElement="{escape(sid)}" id="BPMNShape_{escape(sid)}">')
        out.append(
            f'                <dc:Bounds height="{float(h)}" width="{float(w)}" x="{float(x)}" y="{float(y)}"/>'
        )
        out.append("            </bpmndi:BPMNShape>")
    for eid, s, t in edges:
        sx, sy = center(s)
        tx, ty = center(t)
        out.append(
            f'            <bpmndi:BPMNEdge bpmnElement="{escape(eid)}" id="BPMNEdge_{escape(eid)}" '
            f'sourceElement="BPMNShape_{escape(s)}" targetElement="BPMNShape_{escape(t)}">'
        )
        out.append(f'                <di:waypoint x="{float(sx)}" xsi:type="dc:Point" y="{float(sy)}"/>')
        out.append(f'                <di:waypoint x="{float(tx)}" xsi:type="dc:Point" y="{float(ty)}"/>')
        out.append("            </bpmndi:BPMNEdge>")
    out.append("        </bpmndi:BPMNPlane>")
    out.append("    </bpmndi:BPMNDiagram>")
    return "\n".join(out)


def seq_base(flow: dict, bi: int) -> int:
    """Starting SequenceFlow index for branch bi (mirrors emitter counting)."""
    total = 0
    branches, _ = _branch_chains(flow)
    for i, b in enumerate(branches, start=1):
        if i == bi:
            return total
        total += len(b["nodes"]) + 1
    return total


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
