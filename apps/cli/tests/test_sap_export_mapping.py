"""B-3: XSLTMapping exporter shape — SAP-authored reference, mirrored verbatim.

References:
  - Tenant ground truth (RUNNING flow): IntegrationSuiteAlertingFramework/
    Send_Cloud_Integration_Error_Messages_to_ANS — static dialect
    (mappingSource=mappingSrcIflow, mappingpath, mappinguri, mappingname).
  - Hub TPM V2 export (operator download 2026-09-04): property-set
    confirmation + bundle resource layout (mapping/*.xsl).
  - packages/pattern-book/shapes/Mapping-XSLTMapping.yaml
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.compiler.sap_export import build_cpi_bundle  # noqa: E402

XSL = """<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="2.0">
  <xsl:template match="/"><out><xsl:value-of select="upper-case(//id)"/></out></xsl:template>
</xsl:stylesheet>
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "mappings").mkdir()
    (tmp_path / "mappings" / "order.xsl").write_text(XSL, encoding="utf-8")
    return tmp_path


def _flow(resource: str) -> dict:
    return {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationFlow",
        "metadata": {"id": "map-test", "name": "map-test", "version": 1, "labels": {}},
        "spec": {
            "entrypoints": [{
                "id": "sender-main", "type": "sender.http",
                "config": {"path": "/map_test", "methods": ["POST"]},
                "fidelity": "simulated",
            }],
            "nodes": [
                {"id": "transform", "type": "transform.xslt",
                 "config": {"resource": resource}, "fidelity": "compatible-subset"},
                {"id": "pd-terminator", "type": "receiver.processdirect",
                 "config": {"address": "/map_test_pd"}, "fidelity": "simulated"},
            ],
            "edges": [
                {"from": "sender-main", "to": "transform"},
                {"from": "transform", "to": "pd-terminator"},
            ],
            "extensions": {},
        },
    }


def _iflw_of(bundle: bytes) -> str:
    zf = zipfile.ZipFile(io.BytesIO(bundle))
    return next(zf.read(n) for n in zf.namelist() if n.endswith(".iflw")).decode()


class TestMappingShape:
    def test_mapping_bundles_resource_and_dialect(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        bundle, _ = build_cpi_bundle(_flow("mappings/order.xsl"), project_root=root)
        zf = zipfile.ZipFile(io.BytesIO(bundle))
        # resource rides at mapping/<name>.xsl (reference layout)
        assert "src/main/resources/mapping/order.xsl" in zf.namelist()
        assert zf.read("src/main/resources/mapping/order.xsl").decode() == XSL
        xml = _iflw_of(bundle)
        # static dialect, verbatim
        assert re.search(
            r"<key>mappinguri</key>\s*<value>dir://mapping/xslt/src/main/resources/mapping/order\.xsl</value>", xml
        )
        assert re.search(r"<key>mappingname</key>\s*<value>order</value>", xml)
        assert re.search(r"<key>mappingpath</key>\s*<value>src/main/resources/mapping/order</value>", xml)
        assert re.search(r"<key>mappingSource</key>\s*<value>mappingSrcIflow</value>", xml)
        assert re.search(r"<key>subActivityType</key>\s*<value>XSLTMapping</value>", xml)
        assert re.search(r"<key>componentVersion</key>\s*<value>1\.2</value>", xml)
        assert re.search(
            r"<key>cmdVariantUri</key>\s*<value>ctype::FlowstepVariant/cname::XSLTMapping/version::1\.2\.0</value>", xml
        )
        assert re.search(r"<key>activityType</key>\s*<value>Mapping</value>", xml)

    def test_missing_resource_refused_loudly(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        flow = _flow("")  # no resource
        try:
            build_cpi_bundle(flow, project_root=root)
            raise AssertionError("must refuse mapping without config.resource")
        except ValueError as exc:
            assert "requires config.resource" in str(exc)

    def test_missing_resource_file_refused(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        flow = _flow("mappings/nope.xsl")
        try:
            build_cpi_bundle(flow, project_root=root)
            raise AssertionError("must refuse missing mapping file")
        except ValueError as exc:
            assert "mapping source not found" in str(exc)

    def test_deterministic_build(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        b1, d1 = build_cpi_bundle(_flow("mappings/order.xsl"), project_root=root)
        b2, d2 = build_cpi_bundle(_flow("mappings/order.xsl"), project_root=root)
        assert d1 == d2 and b1 == b2

    def test_transform_xslt_is_now_a_shippable_piece(self) -> None:
        """B-2's shippable-piece law + B-3's exporter shape: the Saxon bridge
        (runtime-real) + XSLTMapping (exporter-renderable) make transform.xslt
        a piece — the intersection flips TRUE."""
        from oiw.agent.turbo_pieces import proven_pieces

        assert "transform.xslt" in proven_pieces()
