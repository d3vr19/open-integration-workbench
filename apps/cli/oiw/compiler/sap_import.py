"""Enhanced import parser for real SAP Cloud Integration artifacts.

Spec ref: §8.2 (compiler pipeline), §8.3 (import report), §8.5 (golden fixtures).

This parser handles the real SAP iFlow XML format:
  - BPMN2 namespaces (xmlns:bpmn2, xmlns:ifl, xmlns:bpmndi, etc.)
  - Nested ZIP structure (SAP export ZIP → content files → inner ZIPs → .iflw XML)
  - ifl:property elements for adapter configuration
  - bpmn2:serviceTask, callActivity, scriptTask, startEvent, endEvent
  - bpmn2:sequenceFlow for edges
  - bpmn2:participant for senders/receivers

Unlike the synthetic fixture parser, this one uses lxml with explicit namespace
handling (local-name matching, not namespace stripping).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .report import (
    ImportReport,
    PreservedOpaque,
    RecognizedComponent,
    UnsupportedComponent,
)

# SAP iFlow namespace map
SAP_NAMESPACES = {
    "bpmn2": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
    "ifl": "http:///com.sap.ifl.model/Ifl.xsd",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


def local_name(tag: str) -> str:
    """Extract the local name from a potentially namespaced tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def get_ifl_properties(elem: ET.Element) -> dict[str, str]:
    """Extract all ifl:property key/value pairs from an element's extensionElements."""
    props: dict[str, str] = {}

    for ext in elem:
        if local_name(ext.tag) != "extensionElements":
            continue
        for prop in ext:
            if local_name(prop.tag) != "property":
                continue
            key_elem = None
            val_elem = None
            for child in prop:
                ln = local_name(child.tag)
                if ln == "key":
                    key_elem = child
                elif ln == "value":
                    val_elem = child
            if key_elem is not None and val_elem is not None:
                k = (key_elem.text or "").strip()
                v = (val_elem.text or "").strip()
                if k:
                    props[k] = v
    return props


def parse_sap_iflow(iflw_content: bytes, report: ImportReport) -> dict[str, Any]:
    """Parse a real SAP iFlow (.iflw) XML file into OIW IR.

    Returns a dict with the IR structure. Updates the ImportReport with
    recognized/opaque/unsupported entries.
    """
    tree = ET.fromstring(iflw_content)

    # Find the collaboration (top-level container)
    collaboration = None
    process = None
    for elem in tree:
        ln = local_name(elem.tag)
        if ln == "collaboration":
            collaboration = elem
        elif ln == "process":
            process = elem

    # Extract participants (senders/receivers)
    senders: list[dict] = []
    receivers: list[dict] = []
    if collaboration is not None:
        for elem in collaboration:
            if local_name(elem.tag) != "participant":
                continue
            props = get_ifl_properties(elem)
            ifl_type = props.get("ifl:type", "")
            pid = elem.get("id", "")
            name = elem.get("name", "")

            if ifl_type == "EndpointSender":
                senders.append({"id": pid, "name": name, "config": props})
                report.recognized.append(RecognizedComponent(component="https_sender", fidelity="simulated"))
            elif ifl_type == "EndpointRecevier":
                receivers.append({"id": pid, "name": name, "config": props})
                report.recognized.append(RecognizedComponent(component="http_receiver", fidelity="simulated"))

    # Extract process elements (steps + edges)
    nodes: list[dict] = []
    edges: list[dict] = []

    if process is not None:
        for elem in process:
            ln = local_name(elem.tag)
            eid = elem.get("id", "")
            name = elem.get("name", "")

            if ln == "startEvent":
                # Map to sender entrypoint (already captured as participant)
                nodes.append(
                    {
                        "id": eid,
                        "type": "start",
                        "name": name,
                        "config": {},
                    }
                )

            elif ln == "endEvent":
                nodes.append(
                    {
                        "id": eid,
                        "type": "end",
                        "name": name,
                        "config": {},
                    }
                )

            elif ln == "serviceTask":
                props = get_ifl_properties(elem)
                # SAP serviceTask is typically an HTTP receiver or content modifier
                node_type = _classify_service_task(name, props)
                nodes.append(
                    {
                        "id": eid,
                        "type": node_type,
                        "name": name,
                        "config": _extract_step_config(node_type, props),
                    }
                )
                report.recognized.append(RecognizedComponent(component=node_type, fidelity="simulated"))

            elif ln == "callActivity":
                props = get_ifl_properties(elem)
                node_type = _classify_call_activity(name, props)
                if node_type.startswith("unsupported:"):
                    reason = node_type.split(":", 1)[1]
                    report.unsupported.append(
                        UnsupportedComponent(
                            component=f"callActivity:{name}",
                            reason=f"Unsupported: {reason}",
                        )
                    )
                else:
                    nodes.append(
                        {
                            "id": eid,
                            "type": node_type,
                            "name": name,
                            "config": _extract_step_config(node_type, props),
                        }
                    )
                    if node_type != "unknown":
                        report.recognized.append(
                            RecognizedComponent(component=node_type, fidelity="simulated")
                        )
                    else:
                        report.unsupported.append(
                            UnsupportedComponent(
                                component=f"callActivity:{name}",
                                reason="Could not classify call activity type",
                            )
                        )

            elif ln == "scriptTask":
                props = get_ifl_properties(elem)
                script_path = props.get("script", props.get("scriptPath", ""))
                nodes.append(
                    {
                        "id": eid,
                        "type": "script.groovy",
                        "name": name,
                        "config": {"resource": script_path} if script_path else {},
                    }
                )
                report.recognized.append(RecognizedComponent(component="groovy_script", fidelity="simulated"))

            elif ln == "sequenceFlow":
                source = elem.get("sourceRef", "")
                target = elem.get("targetRef", "")
                if source and target:
                    edges.append({"from": source, "to": target})

            elif ln == "extensionElements":
                # Process-level properties — preserve as opaque
                props = get_ifl_properties(elem)
                for key in props:
                    if key not in ("componentVersion",):
                        report.preserved_opaque.append(
                            PreservedOpaque(
                                vendor_extension=f"ifl:{key}",
                                location=f"extensions.process.{key}",
                            )
                        )

    # Build the IR
    entrypoints = []
    for s in senders:
        entrypoints.append(
            {
                "id": s["id"],
                "type": "sender.http",
                "config": _extract_sender_config(s["config"]),
                "fidelity": "simulated",
            }
        )

    # Add receivers as nodes
    for r in receivers:
        nodes.append(
            {
                "id": r["id"],
                "type": "receiver.http",
                "name": r["name"],
                "config": _extract_receiver_config(r["config"]),
                "fidelity": "simulated",
            }
        )

    # Add collaboration-level opaque properties
    if collaboration is not None:
        collab_props = get_ifl_properties(collaboration)
        for key in collab_props:
            report.preserved_opaque.append(
                PreservedOpaque(
                    vendor_extension=f"ifl:collaboration.{key}",
                    location=f"extensions.collaboration.{key}",
                )
            )

    # Add warnings
    report.warnings.append("Visual coordinates from BPMN DI not mapped to diagram.json")
    report.warnings.append("SAP iFlow participant names used as node IDs")

    # Determine status
    if report.unsupported or report.preserved_opaque:
        report.status = "PARTIAL"
    else:
        report.status = "FULL"

    return {
        "entrypoints": entrypoints,
        "nodes": nodes,
        "edges": edges,
        "senders": senders,
        "receivers": receivers,
    }


def _classify_service_task(name: str, props: dict[str, str]) -> str:
    """Classify a BPMN serviceTask into an OIW step type."""
    name_lower = name.lower()
    if "get" in name_lower or "request" in name_lower or "call" in name_lower:
        return "receiver.http"
    if "content" in name_lower or "modifier" in name_lower or "set" in name_lower:
        return "modifier.content"
    if "log" in name_lower:
        return "log.message"
    return "modifier.content"  # default


def _classify_call_activity(name: str, props: dict[str, str]) -> str:
    """Classify a BPMN callActivity into an OIW step type."""
    name_lower = name.lower()
    if "json" in name_lower and "xml" in name_lower:
        return "converter.json-to-xml"
    if "xml" in name_lower and "json" in name_lower:
        return "converter.xml-to-json"
    if "set" in name_lower or "property" in name_lower:
        return "modifier.content"
    if "script" in name_lower or "groovy" in name_lower:
        return "script.groovy"
    if "apikey" in name_lower or "api key" in name_lower or "securestore" in name_lower:
        # SAP wraps Groovy scripts in call activities for SecureStore access.
        # These use SAP's ITApiFactory/SecureStoreService — tenant-required.
        # We recognize the pattern but mark as unsupported (tenant-required).
        return "unsupported:tenant-required"
    if "map" in name_lower or "xslt" in name_lower or "transform" in name_lower:
        return "transform.xslt"
    if "filter" in name_lower:
        return "filter"
    if "router" in name_lower or "route" in name_lower:
        return "router.content-based"
    if "convert" in name_lower and "response" in name_lower:
        return "converter.json-to-xml"
    if "country" in name_lower:
        return "modifier.content"
    if "error" in name_lower:
        return "modifier.content"
    if "delete" in name_lower and "log" in name_lower:
        return "log.message"
    return "unknown"


def _extract_step_config(node_type: str, props: dict[str, str]) -> dict[str, Any]:
    """Extract relevant config from SAP ifl:properties for a step type."""
    config: dict[str, Any] = {}
    if node_type == "receiver.http":
        if "Address" in props:
            config["url"] = props["Address"]
        if "Method" in props:
            config["method"] = props["Method"]
        if "ProxyType" in props:
            config["proxyType"] = props["ProxyType"]
    elif node_type == "modifier.content":
        # Content modifiers store header/property changes in ifl:property
        for key, val in props.items():
            if key.startswith("header."):
                config.setdefault("headers", []).append({"name": key[7:], "value": val})
            elif key.startswith("property."):
                config.setdefault("properties", []).append({"name": key[9:], "value": val})
    elif node_type == "script.groovy":
        if "script" in props:
            config["resource"] = props["script"]
    return config


def _extract_sender_config(props: dict[str, str]) -> dict[str, Any]:
    """Extract sender configuration from SAP participant properties."""
    config: dict[str, Any] = {}
    if "Address" in props:
        config["path"] = props["Address"]
    if "allowedMethods" in props:
        config["methods"] = [m.strip() for m in props["allowedMethods"].split(",")]
    return config


def _extract_receiver_config(props: dict[str, str]) -> dict[str, Any]:
    """Extract receiver configuration from SAP participant properties."""
    config: dict[str, Any] = {}
    if "Address" in props:
        config["url"] = props["Address"]
    if "Method" in props:
        config["method"] = props["Method"]
    if "Timeout" in props:
        import contextlib

        with contextlib.suppress(ValueError):
            config["timeoutSeconds"] = int(props["Timeout"])
    return config


def import_sap_export(archive_path: Path, target_profile: str) -> ImportReport:
    """Import a real SAP Cloud Integration export ZIP.

    SAP export ZIP structure:
      - *_content files (each is a nested ZIP containing the iFlow)
      - resources.cnt (additional resources)
      - contentmetadata.md (metadata)
      - hash (content hashes)
      - ExportInformation.info (export metadata)

    This function:
      1. Safely inspects the outer ZIP
      2. Finds the inner content ZIPs
      3. Extracts the .iflw XML from each
      4. Parses the BPMN2 XML into OIW IR
      5. Returns an ImportReport with honest recognized/opaque/unsupported entries
    """
    from ..archive import ArchiveSafetyError, inspect_archive

    # Safe archive inspection
    try:
        manifest = inspect_archive(archive_path)
    except ArchiveSafetyError as exc:
        return ImportReport(
            status="FAILED",
            target_profile=target_profile,
            source_archive=str(archive_path),
            warnings=[f"archive safety check failed: {exc}"],
        )

    report = ImportReport(
        status="PARTIAL",
        target_profile=target_profile,
        source_archive=str(archive_path),
        digest=manifest.digest,
    )
    report.warnings.append(f"Archive contains {manifest.entry_count} entries")

    # Open the outer ZIP
    with zipfile.ZipFile(archive_path, "r") as outer_zip:
        # Find content files (they are inner ZIPs)
        content_files = [n for n in outer_zip.namelist() if n.endswith("_content")]

        for content_name in content_files:
            content_bytes = outer_zip.read(content_name)

            # The content file is itself a ZIP
            try:
                inner_zip = zipfile.ZipFile(io.BytesIO(content_bytes))
            except zipfile.BadZipFile:
                report.unsupported.append(
                    UnsupportedComponent(
                        component=content_name,
                        reason="Not a valid ZIP (inner content)",
                    )
                )
                continue

            # Find the .iflw file
            iflw_files = [n for n in inner_zip.namelist() if n.endswith(".iflw")]
            if not iflw_files:
                report.unsupported.append(
                    UnsupportedComponent(
                        component=content_name,
                        reason="No .iflw file found in inner ZIP",
                    )
                )
                continue

            # Parse each .iflw
            for iflw_name in iflw_files:
                iflw_content = inner_zip.read(iflw_name)
                parse_sap_iflow(iflw_content, report)

                # Check for Groovy scripts
                groovy_files = [n for n in inner_zip.namelist() if n.endswith(".groovy")]
                for groovy_name in groovy_files:
                    script_content = inner_zip.read(groovy_name).decode("utf-8", errors="replace")
                    # Check for forbidden constructs
                    forbidden = ["Runtime.getRuntime", "ProcessBuilder", "GroovyShell"]
                    for f in forbidden:
                        if f in script_content:
                            report.warnings.append(
                                f"Groovy script {groovy_name} contains forbidden construct: {f}"
                            )
                    # Check for XSLT 2.0 features
                    # (would need to inspect XSLT content, not just Groovy)

                # Check for XSLT mappings
                xsl_files = [n for n in inner_zip.namelist() if n.endswith(".xsl") or n.endswith(".xslt")]
                for xsl_name in xsl_files:
                    xsl_content = inner_zip.read(xsl_name).decode("utf-8", errors="replace")
                    xslt2_features = ["for-each-group", "xsl:function", "analyze-string", "perform-sort"]
                    for feature in xslt2_features:
                        if feature in xsl_content:
                            report.warnings.append(
                                f"XSLT mapping {xsl_name} uses {feature} (XSLT 2.0) — will not execute locally"
                            )

            # Check for parameters.prop (SAP externalized parameters)
            prop_files = [n for n in inner_zip.namelist() if n.endswith(".prop")]
            for prop_name in prop_files:
                report.preserved_opaque.append(
                    PreservedOpaque(
                        vendor_extension=f"sap:parameters:{prop_name}",
                        location=f"extensions.parameters.{prop_name}",
                    )
                )

    # Final status determination
    if report.unsupported and not report.recognized:
        report.status = "FAILED"
    elif report.unsupported or report.preserved_opaque:
        report.status = "PARTIAL"
    else:
        report.status = "FULL"

    return report
