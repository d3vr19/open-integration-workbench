"""Golden test: import a real SAP Cloud Integration artifact.

Spec ref: §8.5 (Golden Fixture Repository), §8.3 (Import Report Format).

This is the single most important credibility test for the compatibility
compiler. It breaks the closed-loop self-validation by importing a real
SAP artifact (from the SAP-samples CodeJam repo) and verifying the import
report is honest.

Source: https://github.com/SAP-samples/connecting-systems-services-integration-suite-codejam
Artifact: "Connecting Systems CodeJam - Export.zip"
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oiw.compiler.sap_import import import_sap_export

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FIXTURE = REPO_ROOT / "packages" / "test-fixtures" / "real-sap" / "sap-codejam-request-employee-dependants"


@pytest.fixture()
def archive() -> Path:
    path = FIXTURE / "source.zip"
    if not path.exists():
        pytest.skip(f"real SAP fixture not found: {path}")
    return path


def test_import_sap_export_returns_partial_status(archive: Path) -> None:
    """A real SAP artifact should produce PARTIAL status (not FULL or FAILED).

    FULL would be suspicious — it would mean we perfectly understood every
    SAP-specific extension. FAILED would mean we couldn't parse anything.
    PARTIAL is the honest outcome.
    """
    report = import_sap_export(archive, "sap-cloud-integration-2026-07")
    assert report.status == "PARTIAL", (
        f"Expected PARTIAL for real SAP artifact, got {report.status}. "
        f"Recognized: {len(report.recognized)}, Opaque: {len(report.preserved_opaque)}, "
        f"Unsupported: {len(report.unsupported)}"
    )


def test_import_sap_export_recognizes_senders_and_receivers(archive: Path) -> None:
    """The import should recognize HTTP senders and receivers from the BPMN participants."""
    report = import_sap_export(archive, "sap-cloud-integration-2026-07")
    components = [r.component for r in report.recognized]
    assert "https_sender" in components, "No HTTP sender recognized"
    assert "http_receiver" in components, "No HTTP receiver recognized"


def test_import_sap_export_preserves_opaque_extensions(archive: Path) -> None:
    """SAP-specific properties should be preserved as opaque extensions, not dropped."""
    report = import_sap_export(archive, "sap-cloud-integration-2026-07")
    assert len(report.preserved_opaque) > 0, "No opaque extensions preserved"
    # Should include SAP collaboration properties
    extensions = [p.vendor_extension for p in report.preserved_opaque]
    assert any(
        "collaboration" in e for e in extensions
    ), f"No collaboration properties preserved. Extensions: {extensions[:5]}"


def test_import_sap_export_reports_unsupported_components(archive: Path) -> None:
    """Components that OIW can't handle should be in the unsupported list with reasons."""
    report = import_sap_export(archive, "sap-cloud-integration-2026-07")
    assert len(report.unsupported) > 0, "No unsupported components reported"
    # Each unsupported component should have a reason
    for u in report.unsupported:
        assert u.reason, f"Unsupported component '{u.component}' has no reason"


def test_import_sap_export_includes_warnings(archive: Path) -> None:
    """The import should produce warnings about limitations (visual coords, SAP-specific features)."""
    report = import_sap_export(archive, "sap-cloud-integration-2026-07")
    assert len(report.warnings) > 0, "No warnings produced"
    warning_text = " ".join(report.warnings)
    assert (
        "Visual coordinates" in warning_text or "BPMN DI" in warning_text
    ), f"Expected warning about visual coordinates. Warnings: {report.warnings[:3]}"


def test_import_sap_export_has_digest(archive: Path) -> None:
    """The import report should include a content digest for traceability."""
    report = import_sap_export(archive, "sap-cloud-integration-2026-07")
    assert report.digest is not None
    assert report.digest.startswith("sha256:")


def test_import_sap_export_finds_groovy_scripts(archive: Path) -> None:
    """The export contains iFlow variants with Groovy scripts.

    SAP uses callActivity (not scriptTask) for Groovy scripts, and the script
    file is stored in the inner ZIP. The import should recognize Groovy files
    and produce warnings about SAP SecureStoreService usage.
    """
    report = import_sap_export(archive, "sap-cloud-integration-2026-07")
    # The Groovy scripts in this export use SAP SecureStoreService — they
    # should be classified as unsupported (tenant-required), not script.groovy.
    # But the import should warn about the SAP-specific API usage.
    assert len(report.warnings) > 0
    # Check that the import detected the Groovy files (either as recognized
    # script.groovy or as unsupported tenant-required components)
    has_groovy_reference = (
        any("groovy" in r.component.lower() for r in report.recognized)
        or any(
            "apikey" in u.component.lower() or "securestore" in u.reason.lower() for u in report.unsupported
        )
        or any("groovy" in w.lower() for w in report.warnings)
    )
    assert has_groovy_reference, "No Groovy script reference found in recognized, unsupported, or warnings"
