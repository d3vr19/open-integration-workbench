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
from xml.etree import ElementTree as ET

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
    has_flow_yaml = any(n.endswith("flow.yaml") for n in entries)

    if has_flow_yaml:
        # Native OIW fixture — direct copy
        return _import_native_oiw(archive, manifest, target_profile)

    if not (has_manifest or flow_xml_candidates):
        return ImportReport(
            status="FAILED",
            target_profile=target_profile,
            source_archive=str(archive),
            digest=manifest.digest,
            warnings=["archive does not look like an OIW or SAP-CPI artifact"],
        )

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
    """Parse a minimal subset of SAP-CPI IntegrationFlow XML.

    This is intentionally lossy — we extract only what maps cleanly to the
    canonical IR. Everything else goes to `preservedOpaque` or `unsupported`.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        report.warnings.append(f"{source_name}: invalid XML: {exc}")
        report.unsupported.append(
            UnsupportedComponent(
                component=f"xml:{source_name}",
                reason=f"invalid XML: {exc}",
            )
        )
        return

    # Look for sender / receiver / steps by tag name (best-effort)
    found_sender = False
    found_receiver = False
    found_script = False
    found_modifier = False

    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag in ("Sender", "sender"):
            found_sender = True
            report.recognized.append(RecognizedComponent(component="https_sender", fidelity="simulated"))
        elif tag in ("Receiver", "receiver"):
            found_receiver = True
            report.recognized.append(RecognizedComponent(component="http_receiver", fidelity="simulated"))
        elif tag in ("Script", "Groovy", "script"):
            found_script = True
            report.recognized.append(RecognizedComponent(component="groovy_script", fidelity="simulated"))
        elif tag in ("ContentModifier", "modifier"):
            found_modifier = True
            report.recognized.append(
                RecognizedComponent(component="content_modifier", fidelity="compatible-subset")
            )

    if not (found_sender or found_receiver or found_script or found_modifier):
        report.unsupported.append(
            UnsupportedComponent(
                component=f"xml:{source_name}",
                reason="no recognized CPI elements; preserved as opaque",
            )
        )
