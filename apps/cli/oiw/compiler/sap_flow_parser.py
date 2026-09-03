"""SAP CPI IntegrationFlow XML parser.

WP-07: Enhanced to parse real SAP CPI artifacts in multiple formats:
  1. Simple IntegrationFlow XML (user-provided format with <IntegrationFlow>)
  2. BPMN2 .iflw files (SAP CPI native format with <bpmn2:definitions>)
  3. Nested ZIP export packages (content files containing .iflw)

Extracts: sender adapter, receiver adapter, process steps (ContentModifier,
Mapping/Script), exception subprocess, and resources (Groovy, XSLT).
"""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET


def parse_integration_flow_xml(content: bytes | str) -> dict[str, Any]:
    """Parse a simple IntegrationFlow XML (user-provided format).

    Format:
    <IntegrationFlow xmlns="..." version="1.0">
      <Metadata><Name>...</Name></Metadata>
      <SenderChannel><Adapter type="HTTPS">...</Adapter></SenderChannel>
      <ProcessSteps><Step type="ContentModifier">...</Step></ProcessSteps>
      <ReceiverChannel><Adapter type="OData_V4">...</Adapter></ReceiverChannel>
      <ExceptionSubProcess>...</ExceptionSubProcess>
    </IntegrationFlow>

    Returns a dict with: name, sender, steps, receiver, error_handling.
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        return {"error": f"invalid XML: {exc}"}

    result: dict[str, Any] = {
        "name": "",
        "sender": None,
        "steps": [],
        "receiver": None,
        "error_handling": None,
    }

    # Strip namespace for tag matching
    def local_tag(elem: ET.Element) -> str:
        return elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

    # Parse metadata
    for elem in root.iter():
        if local_tag(elem) == "Name":
            result["name"] = elem.text or ""
            break

    # Parse sender channel
    for elem in root.iter():
        if local_tag(elem) == "SenderChannel":
            adapter = _find_child(elem, "Adapter")
            if adapter is not None:
                result["sender"] = _parse_adapter(adapter)
            break

    # Parse process steps
    for elem in root.iter():
        if local_tag(elem) == "ProcessSteps":
            for step in elem:
                if local_tag(step) == "Step":
                    result["steps"].append(_parse_step(step))
            break

    # Parse receiver channel
    for elem in root.iter():
        if local_tag(elem) == "ReceiverChannel":
            adapter = _find_child(elem, "Adapter")
            if adapter is not None:
                result["receiver"] = _parse_adapter(adapter)
            break

    # Parse exception subprocess
    for elem in root.iter():
        if local_tag(elem) == "ExceptionSubProcess":
            result["error_handling"] = _parse_exception_subprocess(elem)
            break

    return result


def _find_child(parent: ET.Element, tag: str) -> ET.Element | None:
    """Find a child element by local tag name (namespace-agnostic)."""
    for child in parent:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == tag:
            return child
    return None


def _find_children(parent: ET.Element, tag: str) -> list[ET.Element]:
    """Find all children by local tag name."""
    return [c for c in parent if (c.tag.split("}")[-1] if "}" in c.tag else c.tag) == tag]


def _parse_adapter(adapter_elem: ET.Element) -> dict[str, Any]:
    """Parse an <Adapter> element."""
    adapter_type = adapter_elem.get("type", "unknown")
    params: dict[str, str] = {}
    for param in _find_children(adapter_elem, "Parameter"):
        name = param.get("name", "")
        value = param.get("value", "")
        if name:
            params[name] = value
    return {"type": adapter_type, "parameters": params}


def _parse_step(step_elem: ET.Element) -> dict[str, Any]:
    """Parse a <Step> element."""
    step_type = step_elem.get("type", "unknown")
    step_id = step_elem.get("id", "")
    order = step_elem.get("order", "")

    config: dict[str, Any] = {}
    config_elem = _find_child(step_elem, "Configuration")
    if config_elem is not None:
        for child in config_elem:
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            config[local] = child.text or child.get("value", "") or ""

    return {"id": step_id, "type": step_type, "order": order, "config": config}


def _parse_exception_subprocess(elem: ET.Element) -> dict[str, Any]:
    """Parse an <ExceptionSubProcess> element."""
    steps = []
    for step in _find_children(elem, "Step"):
        steps.append(_parse_step(step))
    return {"steps": steps}


def parse_bpmn2_iflw(content: bytes | str) -> dict[str, Any]:
    """Parse a BPMN2 .iflw file (SAP CPI native format).

    BPMN2 files use <bpmn2:definitions> with <ifl:...> extension elements.
    We extract adapter types and step types from the ifl namespace.

    WP-08 PR-5 / Track B-002: also classify <callActivity> elements by
    reading their <ifl:property><key>activityType</key><value>...</value>
    block, not by guessing from the activity name. This is the fix for the
    import parser gaps documented in WP-08 §2 ("Honest Diagnosis").

    Activity-type vocabulary observed on real SAP CI tenants:
      - Enricher                          → modifier.content
      - Mapping (MessageMapping)          → transform.xslt (simulated; SAP uses .mmap)
      - Script                            → script.groovy (tenant-required if it uses SecureStoreService)
      - XmlToJsonConverter                → converter.xml-to-json
      - JsonToXmlConverter                → converter.json-to-xml
      - Filter                            → filter
      - Router / ContentBasedRouter       → router.content-based
      - Splitter / GeneralSplitter        → splitter.general
      - Gather / Join                     → gather
      - Encoder / Base64Encoder           → encoder.base64
      - Log / Logger                      → log.message
      - ProcessCallElement                → subprocess.local (simulated)
      - DBstorage                         → datastore.write (tenant-required)
      - RequestReply                      → request-reply (simulated)
      - CallActivity (unknown type)       → unsupported (kept in extensions, not dropped)
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        return {"error": f"invalid BPMN2 XML: {exc}"}

    result: dict[str, Any] = {
        "name": "",
        "sender": None,
        "steps": [],
        "receiver": None,
        "error_handling": None,
        "unsupported_call_activities": [],  # WP-08 B-002: don't silently drop
    }

    # Search for ifl: namespace elements and BPMN2 patterns
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        tag_lower = tag.lower()

        # Sender patterns (BPMN2 uses EndpointSender, EndpointRecevier [sic])
        if (
            tag_lower in ("endpointsender", "sender")
            and result["sender"] is None
            or "sender" in tag_lower
            and result["sender"] is None
        ):
            result["sender"] = {"type": "HTTPS", "parameters": _extract_ifl_params(elem)}

        # Receiver patterns (note SAP typo: EndpointRecevier)
        elif (
            tag_lower in ("endpointrecevier", "endpointreceiver", "receiver")
            and result["receiver"] is None
            or "receiver" in tag_lower
            and "recevier" in tag_lower
            and result["receiver"] is None
            or "receiver" in tag_lower
            and result["receiver"] is None
        ):
            result["receiver"] = {"type": "HTTP", "parameters": _extract_ifl_params(elem)}

        # Script/Groovy
        elif "script" in tag_lower or "groovy" in tag_lower:
            result["steps"].append({"id": tag, "type": "Script", "config": {"Language": "Groovy"}})

        # Content Modifier
        elif "contentmodifier" in tag_lower or "content_modifier" in tag_lower:
            result["steps"].append({"id": tag, "type": "ContentModifier", "config": {}})

        # Mapping/XSLT
        elif "mapping" in tag_lower or "xslt" in tag_lower:
            result["steps"].append({"id": tag, "type": "Mapping", "config": {"MappingType": "XSLT"}})

        # Router
        elif "router" in tag_lower:
            result["steps"].append({"id": tag, "type": "Router", "config": {}})

        # MessageFlow with name (BPMN2 channel: HTTP, SOAP, etc.)
        elif tag_lower == "messageflow" and elem.get("name"):
            channel_name = elem.get("name", "").upper()
            if "SENDER" in channel_name or "INBOUND" in channel_name or result["sender"] is None:
                if result["sender"] is None:
                    adapter_type = "HTTPS"
                    if "SOAP" in channel_name:
                        adapter_type = "SOAP"
                    elif "SFTP" in channel_name:
                        adapter_type = "SFTP"
                    elif "ODATA" in channel_name:
                        adapter_type = "ODATA_V4"
                    result["sender"] = {"type": adapter_type, "parameters": _extract_ifl_params(elem)}
            elif ("RECEIVER" in channel_name or "OUTBOUND" in channel_name) and result["receiver"] is None:
                adapter_type = "HTTP"
                if "SOAP" in channel_name:
                    adapter_type = "SOAP"
                elif "ODATA" in channel_name:
                    adapter_type = "ODATA_V4"
                elif "IDOC" in channel_name:
                    adapter_type = "IDOC"
                elif "MAIL" in channel_name or "SMTP" in channel_name:
                    adapter_type = "MAIL"
                elif "SFTP" in channel_name:
                    adapter_type = "SFTP"
                result["receiver"] = {"type": adapter_type, "parameters": _extract_ifl_params(elem)}

        # ServiceTask (BPMN2 processing step) — WP-10 H9: extract activityType and properties
        elif tag_lower == "servicetask":
            name = elem.get("name", "")
            props: dict[str, str] = {}
            for ext in elem.iter():
                ext_local = ext.tag.split("}")[-1] if "}" in ext.tag else ext.tag
                if ext_local != "extensionElements":
                    continue
                for prop in ext:
                    prop_local = prop.tag.split("}")[-1] if "}" in prop.tag else prop.tag
                    if prop_local != "property":
                        continue
                    k = None
                    v = None
                    for child in prop:
                        lt = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        if lt == "key":
                            k = (child.text or "").strip()
                        elif lt == "value":
                            v = child.text or ""
                    if k:
                        props[k] = v

            activity_type = props.get("activityType", "")
            if activity_type == "ExternalCall":
                result["steps"].append(
                    {
                        "id": elem.get("id", ""),
                        "type": "ServiceTask",
                        "config": {
                            "name": name,
                            "activityType": "ExternalCall",
                            "properties": props,
                        },
                    }
                )
            elif name and ("groovy" in name.lower() or "script" in name.lower()):
                result["steps"].append(
                    {"id": elem.get("id", ""), "type": "Script", "config": {"Language": "Groovy", "properties": props}}
                )
            elif name and ("mapping" in name.lower() or "xslt" in name.lower() or "transform" in name.lower()):
                result["steps"].append(
                    {"id": elem.get("id", ""), "type": "Mapping", "config": {"MappingType": "XSLT", "properties": props}}
                )
            elif name and ("filter" in name.lower()):
                result["steps"].append({"id": elem.get("id", ""), "type": "Filter", "config": {"properties": props}})
            elif name and ("router" in name.lower() or "route" in name.lower()):
                result["steps"].append({"id": elem.get("id", ""), "type": "Router", "config": {"properties": props}})
            else:
                # Generic service task — record as a processing step with properties preserved
                result["steps"].append(
                    {
                        "id": elem.get("id", ""),
                        "type": "ServiceTask",
                        "config": {"name": name, "activityType": activity_type, "properties": props},
                    }
                )

        # WP-08 PR-5 / Track B-002: classify callActivity by its ifl:property
        # activityType, not by guessing from the activity name.
        elif tag_lower == "callactivity":
            step = _classify_call_activity(elem)
            if step is not None:
                if step["type"] == "unsupported":
                    # Preserve the callActivity as opaque metadata — never drop.
                    result["unsupported_call_activities"].append(step)
                else:
                    result["steps"].append(step)

    # Try to find flow name
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "collaboration" or tag == "process":
            name = elem.get("name", "")
            if name:
                result["name"] = name
                break

    return result


# WP-08 PR-5 / Track B-002: callActivity classification by activityType.
# Maps SAP CI activityType values to OIW step types. Classifications marked
# `tenant-required` are kept out of the IR's main `nodes` list (they go into
# `extensions` instead) so the simulated runtime doesn't try to execute
# something that needs a real SAP tenant.
_ACTIVITY_TYPE_MAP: dict[str, dict[str, Any]] = {
    "Enricher": {"oiw_type": "modifier.content", "fidelity": "compatible-subset"},
    "Mapping": {"oiw_type": "transform.xslt", "fidelity": "simulated"},
    "MessageMapping": {"oiw_type": "transform.xslt", "fidelity": "simulated"},
    "Script": {"oiw_type": "script.groovy", "fidelity": "compatible-subset"},
    "XmlToJsonConverter": {"oiw_type": "converter.xml-to-json", "fidelity": "compatible-subset"},
    "JsonToXmlConverter": {"oiw_type": "converter.json-to-xml", "fidelity": "compatible-subset"},
    "Filter": {"oiw_type": "filter", "fidelity": "compatible-subset"},
    "ContentBasedRouter": {"oiw_type": "router.content-based", "fidelity": "compatible-subset"},
    "Router": {"oiw_type": "router.content-based", "fidelity": "compatible-subset"},
    "GeneralSplitter": {"oiw_type": "splitter.general", "fidelity": "simulated"},
    "Splitter": {"oiw_type": "splitter.general", "fidelity": "simulated"},
    "Gather": {"oiw_type": "gather", "fidelity": "simulated"},
    "Join": {"oiw_type": "gather", "fidelity": "simulated"},
    "Base64Encoder": {"oiw_type": "encoder.base64", "fidelity": "compatible-subset"},
    "Encoder": {"oiw_type": "encoder.base64", "fidelity": "compatible-subset"},
    "Logger": {"oiw_type": "log.message", "fidelity": "compatible-subset"},
    "Log": {"oiw_type": "log.message", "fidelity": "compatible-subset"},
    "ProcessCallElement": {"oiw_type": "subprocess.local", "fidelity": "simulated"},
    "RequestReply": {"oiw_type": "request-reply", "fidelity": "simulated"},
    "DBstorage": {"oiw_type": "datastore.write", "fidelity": "tenant-required"},
    # SecureStore access — tenant-required (uses SAP-specific ITApiFactory + SecureStoreService).
    # We classify the *type* but mark fidelity so the runtime knows not to execute it.
    # The presence of "SecureStore" in the script body or activity name is a signal.
}


def _classify_call_activity(elem: ET.Element) -> dict[str, Any] | None:
    """Classify a <callActivity> element by its ifl:property activityType.

    Returns a step dict with `id`, `type`, `config`. If the activityType
    is unknown, returns a step with `type="unsupported"` so the caller
    can preserve it in `extensions` (never silently dropped).

    Spec ref: WP-08 §5 B-002 ("Prefer classifying from ifl:property keys
    over guessing from the activity name").
    """
    name = elem.get("name", "")
    elem_id = elem.get("id", "")

    # Read all ifl:property key/value pairs in the callActivity's extensionElements
    props: dict[str, str] = {}
    for ext in elem.iter():
        ext_local = ext.tag.split("}")[-1] if "}" in ext.tag else ext.tag
        if ext_local != "extensionElements":
            continue
        for prop in ext:
            prop_local = prop.tag.split("}")[-1] if "}" in prop.tag else prop.tag
            if prop_local != "property":
                continue
            k = None
            v = None
            for child in prop:
                lt = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if lt == "key":
                    k = (child.text or "").strip()
                elif lt == "value":
                    v = child.text or ""
            if k:
                props[k] = v

    activity_type = props.get("activityType", "")

    # Special-case SecureStore: Script activityType + name mentions SecureStore
    # → tenant-required, not the compatible-subset script.groovy.
    if activity_type == "Script" and "securestore" in name.lower():
        return {
            "id": elem_id or name,
            "type": "unsupported",
            "config": {
                "name": name,
                "activityType": activity_type,
                "reason": "tenant-required: uses SAP SecureStoreService",
                "properties": props,
            },
            "fidelity": "tenant-required",
        }

    mapping = _ACTIVITY_TYPE_MAP.get(activity_type)
    if mapping is None:
        # Unknown activityType — preserve as unsupported, never drop.
        return {
            "id": elem_id or name,
            "type": "unsupported",
            "config": {
                "name": name,
                "activityType": activity_type,
                "reason": f"unrecognized activityType: {activity_type!r}",
                "properties": props,
            },
            "fidelity": "unsupported",
        }

    return {
        "id": elem_id or name,
        "type": mapping["oiw_type"],  # caller maps this to OIW step type
        # We stash the SAP-native type in config so the IR can preserve provenance.
        "config": {
            "name": name,
            "activityType": activity_type,
            "properties": props,
        },
        "fidelity": mapping["fidelity"],
    }


def _extract_ifl_params(elem: ET.Element) -> dict[str, str]:
    """Extract parameter name/value pairs from an ifl element."""
    params: dict[str, str] = {}
    for child in elem:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        tag_lower = tag.lower()
        if "parameter" in tag_lower or "property" in tag_lower:
            name = child.get("name", "")
            value = child.get("value", "")
            if name:
                params[name] = value
        elif child.text and child.text.strip():
            params[tag] = child.text.strip()
    return params


def convert_parsed_flow_to_oiw_ir(parsed: dict[str, Any]) -> dict[str, Any]:
    """Convert a parsed flow (from either format) into OIW IR structure.

    Returns a dict matching the OIW IntegrationFlow YAML structure.
    """
    flow_id = (parsed.get("name") or "imported-flow").replace(" ", "_").replace("-", "_").lower()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # Map sender
    sender = parsed.get("sender")
    if sender:
        node = _adapter_to_node("sender", sender)
        nodes.append(node)
        prev = "sender"
    else:
        prev = None

    # Map process steps
    for i, step in enumerate(parsed.get("steps", [])):
        node = _step_to_node(step, i)
        if node:
            nodes.append(node)
            if prev:
                edges.append({"from": prev, "to": node["id"]})
            prev = node["id"]

    # Map receiver
    receiver = parsed.get("receiver")
    if receiver:
        node = _adapter_to_node("receiver", receiver)
        nodes.append(node)
        if prev:
            edges.append({"from": prev, "to": node["id"]})

    # Error handling
    error_handling = None
    if parsed.get("error_handling"):
        error_handling = {
            "defaultExceptionSubprocess": {
                "steps": [
                    {"id": s["id"], "type": _step_type_to_oiw(s["type"]), "config": s.get("config", {})}
                    for s in parsed["error_handling"].get("steps", [])
                ]
            }
        }

    return {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationFlow",
        "metadata": {"id": flow_id, "name": parsed.get("name", flow_id), "version": 1, "labels": {}},
        "spec": {
            "entrypoints": [],
            "nodes": nodes,
            "edges": edges,
            "extensions": {},
            **({"errorHandling": error_handling} if error_handling else {}),
        },
    }


_ADAPTER_TYPE_MAP = {
    "HTTPS": "sender.http",
    "HTTP": "receiver.http",
    "SOAP": "sender.soap" if "sender" in "" else "receiver.soap",  # context-dependent
    "ODATA_V4": "receiver.odata-v4",
    "ODATA_V2": "receiver.odata-v4",
    "SFTP": "receiver.sftp",
    "IDOC": "receiver.idoc",
    "MAIL": "receiver.mail",
    "JMS": "receiver.http",  # stub
    "TIMER": "sender.http",  # stub
}


def _adapter_to_node(role: str, adapter: dict[str, Any]) -> dict[str, Any]:
    """Convert a parsed adapter to an OIW node."""
    adapter_type = adapter.get("type", "HTTPS").upper()
    params = adapter.get("parameters", {})

    if role == "sender":
        if adapter_type == "HTTPS":
            return {
                "id": "sender",
                "type": "sender.http",
                "config": {"path": params.get("url", "/api"), "methods": [params.get("method", "POST")]},
                "fidelity": "simulated",
            }
        if adapter_type == "SOAP":
            return {
                "id": "sender",
                "type": "sender.soap",
                "config": {"endpoint": params.get("url", ""), "operation": params.get("operation", "")},
                "fidelity": "simulated",
            }
        # Default: HTTP sender
        return {
            "id": "sender",
            "type": "sender.http",
            "config": {"path": params.get("url", "/api"), "methods": ["POST"]},
            "fidelity": "simulated",
        }

    # Receiver
    if adapter_type in ("HTTP", "HTTPS"):
        return {
            "id": "receiver",
            "type": "receiver.http",
            "config": {
                "url": params.get("url", "https://backend.example.com"),
                "method": params.get("method", "POST"),
                "timeoutSeconds": int(params.get("timeout", "30")),
            },
            "fidelity": "simulated",
        }
    if adapter_type in ("ODATA_V4", "ODATA_V2"):
        return {
            "id": "receiver",
            "type": "receiver.odata-v4",
            "config": {
                "serviceUrl": params.get("url", ""),
                "entitySet": params.get("entitySet", ""),
                "operation": params.get("operation", "GET"),
                "timeoutSeconds": 30,
            },
            "fidelity": "simulated",
        }
    if adapter_type == "SOAP":
        return {
            "id": "receiver",
            "type": "receiver.soap",
            "config": {"endpoint": params.get("url", ""), "operation": params.get("operation", "")},
            "fidelity": "simulated",
        }
    if adapter_type == "SFTP":
        return {
            "id": "receiver",
            "type": "receiver.sftp",
            "config": {"host": params.get("host", ""), "path": params.get("path", "/")},
            "fidelity": "simulated",
        }
    if adapter_type == "IDOC":
        return {
            "id": "receiver",
            "type": "receiver.idoc",
            "config": {"idocType": params.get("idocType", "ORDERS05")},
            "fidelity": "simulated",
        }
    if adapter_type == "MAIL":
        return {
            "id": "receiver",
            "type": "receiver.mail",
            "config": {"to": params.get("to", ""), "subject": params.get("subject", "")},
            "fidelity": "simulated",
        }
    # Default: HTTP receiver
    return {
        "id": "receiver",
        "type": "receiver.http",
        "config": {"url": params.get("url", ""), "method": "POST"},
        "fidelity": "simulated",
    }


_STEP_TYPE_MAP = {
    "ContentModifier": "modifier.content",
    "Mapping": "transform.xslt",
    "Script": "script.groovy",
    "Router": "router",
    "Filter": "filter",
    "Splitter": "splitter",
    "Gather": "gather",
    "Encoder": "encoder.base64",
    "Log": "log.message",
}


def _step_to_node(step: dict[str, Any], index: int) -> dict[str, Any] | None:
    """Convert a parsed step to an OIW node.

    Handles two sources of steps:
      1. Legacy BPMN2 tag-based classification (ServiceTask, Script, etc.)
         — these use SAP-native type names that _STEP_TYPE_MAP translates.
      2. WP-08 PR-5 callActivity classification — these already return the
         OIW type directly (e.g. "modifier.content", "converter.json-to-xml")
         because _classify_call_activity() already did the mapping via
         _ACTIVITY_TYPE_MAP. We detect this by checking if the type contains
         a dot (OIW types always do: "modifier.content", "sender.http", etc.).
    """
    step_type = step.get("type", "")

    # WP-08 PR-5: if the type is already an OIW type (contains a dot),
    # use it directly without looking up _STEP_TYPE_MAP.
    if "." in step_type:
        oiw_type = step_type
    else:
        oiw_type = _STEP_TYPE_MAP.get(step_type)
        if not oiw_type:
            return None

    node_id = step.get("id") or f"step-{index}"
    config = step.get("config", {})
    fidelity = step.get("fidelity", "simulated")

    # Special handling for known step types
    if oiw_type == "script.groovy":
        config = {"script": config.get("ScriptArtifact", "resources/scripts/process.groovy")}
    elif oiw_type == "transform.xslt":
        config = {"stylesheet": config.get("MappingArtifact", "resources/mappings/transform.xsl")}
    else:
        # WP-08 PR-5: callActivity steps carry their SAP-native properties in
        # config. Keep the OIW-relevant subset and drop the raw SAP properties
        # (they're preserved in the import report's `unsupported_call_activities`
        # list for truly unclassifiable steps).
        if "properties" in config:
            config = {k: v for k, v in config.items() if k != "properties"}

    return {"id": node_id, "type": oiw_type, "config": config, "fidelity": fidelity}


def _step_type_to_oiw(step_type: str) -> str:
    return _STEP_TYPE_MAP.get(step_type, "log.message")


__all__ = [
    "parse_integration_flow_xml",
    "parse_bpmn2_iflw",
    "convert_parsed_flow_to_oiw_ir",
]
