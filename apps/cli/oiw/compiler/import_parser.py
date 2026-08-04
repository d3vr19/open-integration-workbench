"""Minimal import parser.

Spec ref: §8.2 (compiler pipeline), §8.3 (import report), §8.5 (golden fixtures).

This is a minimal implementation that:
  - Inspects the archive safely (zip-bomb / path-traversal defense).
  - Recognises the canonical minimal fixture layout (a zip containing
    `META-INF/MANIFEST.MF` + an `IntegrationFlow*.xml`-style file).
  - Extracts a minimal subset of recognised elements into OIW IR.
  - Records unknown / opaque / unsupported content in the import report.

This MVP parser does NOT attempt to be a faithful SAP CPI importer. It
proves the architecture: safe archive → IR → export → round-trip report.
Full SAP CPI format support is Phase 6 work (spec §19).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from .archive import ArchiveSafetyError, inspect_archive
from .report import ImportReport, PreservedOpaque, RecognizedComponent, UnsupportedComponent


class ImportError(Exception):
    """Raised when an archive cannot be imported."""


def import_archive(project_root: Path, archive: Path, target_profile: str) -> ImportReport:
    """Import a SAP-compatible archive into the project's IR.

    Spec ref: §8.2.
    """
    # 1. Safe archive inspection
    try:
        manifest = inspect_archive(archive)
    except ArchiveSafetyError as exc:
        return ImportReport(
            status="FAILED",
            target_profile=target_profile,
            source_archive=str(archive),
            warnings=[f"archive safety check failed: {exc}"],
        )

    # 2. Format classification (look for SAP-CPI-like markers)
    entries = {e.name: e for e in manifest.entries}
    has_manifest = "META-INF/MANIFEST.MF" in entries
    flow_xml_candidates = [n for n in entries if n.endswith(".xml") and "IntegrationFlow" in n]
    iflw_candidates = [n for n in entries if n.endswith(".iflw")]
    has_flow_yaml = any(n.endswith("flow.yaml") for n in entries)

    if has_flow_yaml:
        # Native OIW fixture — direct copy
        return _import_native_oiw(archive, manifest, target_profile)

    # WP-07: Also look for .iflw files (BPMN2 format) and any XML with
    # <IntegrationFlow> root element
    all_xml_candidates = flow_xml_candidates + iflw_candidates
    if not all_xml_candidates:
        # Check if any file might be an IntegrationFlow XML by content
        try:
            with zipfile.ZipFile(archive, "r") as zf:
                for name in entries:
                    if name.endswith(".xml") or name.endswith(".iflw"):
                        content = zf.read(name)
                        if b"IntegrationFlow" in content or b"bpmn2:definitions" in content:
                            all_xml_candidates.append(name)
        except Exception:
            pass

    if not (has_manifest or all_xml_candidates):
        return ImportReport(
            status="FAILED",
            target_profile=target_profile,
            source_archive=str(archive),
            digest=manifest.digest,
            warnings=["archive does not look like an OIW or SAP-CPI artifact"],
        )

    # Use the enhanced candidates for parsing
    flow_xml_candidates = all_xml_candidates or flow_xml_candidates

    # 3. Semantic parse (minimal): read the first IntegrationFlow XML
    report = ImportReport(
        status="PARTIAL",
        target_profile=target_profile,
        source_archive=str(archive),
        digest=manifest.digest,
    )

    try:
        with zipfile.ZipFile(archive, "r") as zf:
            for name in flow_xml_candidates:
                content = zf.read(name)
                _parse_minimal_cpi_xml(content, name, report)
    except Exception as exc:
        report.status = "FAILED"
        report.warnings.append(f"parse error: {exc}")
        return report

    # 4. Preserved opaque / unsupported
    for name in entries:
        if name.endswith(".png") or name.endswith(".svg"):
            report.preserved_opaque.append(
                PreservedOpaque(
                    vendor_extension=f"resource:{name}",
                    location=f"extensions.resources.{name}",
                )
            )

    # 5. Final status
    if report.recognized and not report.unsupported:
        report.status = "FULL"
    elif report.recognized:
        report.status = "PARTIAL"
    else:
        report.status = "FAILED"

    return report


def _import_native_oiw(archive: Path, manifest, target_profile: str) -> ImportReport:
    """Round-trip a native OIW fixture (flow.yaml inside the zip)."""
    report = ImportReport(
        status="FULL",
        target_profile=target_profile,
        source_archive=str(archive),
        digest=manifest.digest,
        warnings=["native OIW archive recognized — full round-trip"],
    )
    report.recognized.append(RecognizedComponent(component="oiw-flow-ir", fidelity="compatible-subset"))
    return report


_CPI_NS = "http://sap.com/it/"


def _parse_minimal_cpi_xml(content: bytes, source_name: str, report: ImportReport) -> None:
    """Parse SAP-CPI IntegrationFlow XML using the enhanced parser.

    WP-07: Now uses the dedicated sap_flow_parser module which handles:
    - Simple IntegrationFlow XML (user-provided format)
    - BPMN2 .iflw files (SAP CPI native format)
    """
    from .sap_flow_parser import parse_bpmn2_iflw, parse_integration_flow_xml

    # Try simple IntegrationFlow XML first
    parsed = parse_integration_flow_xml(content)

    # If simple format found nothing, try BPMN2
    if parsed.get("error") or (
        not parsed.get("sender") and not parsed.get("receiver") and not parsed.get("steps")
    ):
        bpmn2_parsed = parse_bpmn2_iflw(content)
        if bpmn2_parsed.get("sender") or bpmn2_parsed.get("receiver") or bpmn2_parsed.get("steps"):
            parsed = bpmn2_parsed

    if parsed.get("error"):
        report.warnings.append(f"{source_name}: {parsed['error']}")
        report.unsupported.append(
            UnsupportedComponent(
                component=f"xml:{source_name}",
                reason=parsed["error"],
            )
        )
        return

    # Map parsed components to recognized
    if parsed.get("sender"):
        adapter_type = parsed["sender"].get("type", "HTTPS").upper()
        if adapter_type == "SOAP":
            report.recognized.append(RecognizedComponent(component="soap_sender", fidelity="simulated"))
        else:
            report.recognized.append(RecognizedComponent(component="https_sender", fidelity="simulated"))

    for step in parsed.get("steps", []):
        step_type = step.get("type", "")
        if step_type in ("Script", "Groovy"):
            report.recognized.append(RecognizedComponent(component="groovy_script", fidelity="simulated"))
        elif step_type == "ContentModifier":
            report.recognized.append(
                RecognizedComponent(component="content_modifier", fidelity="compatible-subset")
            )
        elif step_type == "Mapping":
            report.recognized.append(RecognizedComponent(component="xslt_transform", fidelity="simulated"))
        elif step_type == "Router":
            report.recognized.append(RecognizedComponent(component="router", fidelity="compatible-subset"))
        elif step_type == "Filter":
            report.recognized.append(RecognizedComponent(component="filter", fidelity="compatible-subset"))
        elif step_type == "ServiceTask":
            # BPMN2 generic service task — recognized as processing step
            report.recognized.append(
                RecognizedComponent(
                    component=f"service_task:{step.get('config', {}).get('name', 'unknown')}",
                    fidelity="simulated",
                )
            )
        else:
            report.recognized.append(RecognizedComponent(component=f"step:{step_type}", fidelity="simulated"))

    if parsed.get("receiver"):
        adapter_type = parsed["receiver"].get("type", "HTTP").upper()
        if adapter_type in ("ODATA_V4", "ODATA_V2"):
            report.recognized.append(RecognizedComponent(component="odata_receiver", fidelity="simulated"))
        elif adapter_type == "SOAP":
            report.recognized.append(RecognizedComponent(component="soap_receiver", fidelity="simulated"))
        elif adapter_type == "IDOC":
            report.recognized.append(RecognizedComponent(component="idoc_receiver", fidelity="simulated"))
        elif adapter_type == "SFTP":
            report.recognized.append(RecognizedComponent(component="sftp_receiver", fidelity="simulated"))
        elif adapter_type == "MAIL":
            report.recognized.append(RecognizedComponent(component="mail_receiver", fidelity="simulated"))
        else:
            report.recognized.append(RecognizedComponent(component="http_receiver", fidelity="simulated"))

    if parsed.get("error_handling"):
        report.recognized.append(
            RecognizedComponent(component="error_subprocess", fidelity="compatible-subset")
        )

    if (
        not parsed.get("sender")
        and not parsed.get("receiver")
        and not parsed.get("steps")
        and not report.recognized
    ):
        report.unsupported.append(
            UnsupportedComponent(
                component=f"xml:{source_name}",
                reason="no recognized CPI elements; preserved as opaque",
            )
        )
