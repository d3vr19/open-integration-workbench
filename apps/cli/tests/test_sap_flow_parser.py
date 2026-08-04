"""Tests for SAP flow parser (WP-07 enhanced import parser).

Covers:
  - Parse simple IntegrationFlow XML (user-provided format)
  - Parse BPMN2 .iflw file (SAP CPI native format)
  - Convert parsed flow to OIW IR
  - Real .iflw file from CodeJam ZIP is parsed
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.compiler.sap_flow_parser import (  # noqa: E402
    convert_parsed_flow_to_oiw_ir,
    parse_bpmn2_iflw,
    parse_integration_flow_xml,
)

SAMPLE_INTEGRATION_FLOW_XML = """<?xml version="1.0" encoding="UTF-8"?>
<IntegrationFlow xmlns="http://cpi-forge.dev/schema/iflw/1.0" version="1.0">
  <Metadata>
    <Name>CustomerSync_iFlow</Name>
    <Description>Synchronize customers from S/4HANA to CRM</Description>
  </Metadata>
  <SenderChannel>
    <Adapter type="HTTPS">
      <Parameter name="url" value="/customersync"/>
      <Parameter name="method" value="POST"/>
    </Adapter>
  </SenderChannel>
  <ProcessSteps>
    <Step id="step_1" type="ContentModifier" order="1">
      <Configuration>
        <Header action="create" name="X-Correlation-ID" value="${header.MessageID}"/>
      </Configuration>
    </Step>
    <Step id="step_2" type="Mapping" order="2">
      <Configuration>
        <MappingType>XSLT</MappingType>
        <MappingArtifact>Customer_S4_to_CRM.xsl</MappingArtifact>
      </Configuration>
    </Step>
    <Step id="step_3" type="Script" order="3">
      <Configuration>
        <Language>Groovy</Language>
        <ScriptArtifact>enrich_customer.groovy</ScriptArtifact>
      </Configuration>
    </Step>
  </ProcessSteps>
  <ReceiverChannel>
    <Adapter type="OData_V4">
      <Parameter name="url" value="https://crm.example.com/odata/v4"/>
      <Parameter name="entitySet" value="Customers"/>
      <Parameter name="operation" value="POST"/>
    </Adapter>
  </ReceiverChannel>
  <ExceptionSubProcess>
    <Step id="exc_1" type="Script">
      <Configuration>
        <Language>Groovy</Language>
        <ScriptArtifact>error_handler.groovy</ScriptArtifact>
      </Configuration>
    </Step>
  </ExceptionSubProcess>
</IntegrationFlow>"""


class TestParseIntegrationFlowXml:
    def test_parse_simple_format(self) -> None:
        """Parse the user-provided IntegrationFlow XML format."""
        parsed = parse_integration_flow_xml(SAMPLE_INTEGRATION_FLOW_XML)
        assert parsed["name"] == "CustomerSync_iFlow"
        assert parsed["sender"] is not None
        assert parsed["sender"]["type"] == "HTTPS"
        assert parsed["sender"]["parameters"]["url"] == "/customersync"
        assert len(parsed["steps"]) == 3
        assert parsed["steps"][0]["type"] == "ContentModifier"
        assert parsed["steps"][1]["type"] == "Mapping"
        assert parsed["steps"][2]["type"] == "Script"
        assert parsed["receiver"] is not None
        assert parsed["receiver"]["type"] == "OData_V4"
        assert parsed["receiver"]["parameters"]["entitySet"] == "Customers"
        assert parsed["error_handling"] is not None
        assert len(parsed["error_handling"]["steps"]) == 1

    def test_parse_invalid_xml(self) -> None:
        """Invalid XML returns error dict."""
        parsed = parse_integration_flow_xml("not xml at all")
        assert "error" in parsed

    def test_parse_empty_flow(self) -> None:
        """Empty IntegrationFlow returns empty fields."""
        parsed = parse_integration_flow_xml(
            '<?xml version="1.0"?><IntegrationFlow xmlns="http://cpi-forge.dev/schema/iflw/1.0"/>'
        )
        assert parsed["name"] == ""
        assert parsed["sender"] is None
        assert parsed["steps"] == []
        assert parsed["receiver"] is None


class TestConvertToOiwIr:
    def test_convert_to_oiw_ir(self) -> None:
        """Parsed flow converts to OIW IR structure."""
        parsed = parse_integration_flow_xml(SAMPLE_INTEGRATION_FLOW_XML)
        ir = convert_parsed_flow_to_oiw_ir(parsed)

        assert ir["apiVersion"] == "oiw.dev/v1alpha1"
        assert ir["kind"] == "IntegrationFlow"
        assert ir["metadata"]["id"] == "customersync_iflow"
        assert len(ir["spec"]["nodes"]) >= 5  # sender + 3 steps + receiver
        assert ir["spec"]["nodes"][0]["type"] == "sender.http"
        assert ir["spec"]["nodes"][-1]["type"] == "receiver.odata-v4"

        # Check edges connect sender → steps → receiver
        assert len(ir["spec"]["edges"]) >= 4

        # Check error handling
        assert "errorHandling" in ir["spec"]

    def test_convert_preserves_adapter_types(self) -> None:
        """OData V4 receiver maps to receiver.odata-v4."""
        parsed = parse_integration_flow_xml(SAMPLE_INTEGRATION_FLOW_XML)
        ir = convert_parsed_flow_to_oiw_ir(parsed)
        receiver = ir["spec"]["nodes"][-1]
        assert receiver["type"] == "receiver.odata-v4"
        assert receiver["config"]["entitySet"] == "Customers"

    def test_convert_step_types_mapped(self) -> None:
        """Step types are mapped to OIW types."""
        parsed = parse_integration_flow_xml(SAMPLE_INTEGRATION_FLOW_XML)
        ir = convert_parsed_flow_to_oiw_ir(parsed)
        types = [n["type"] for n in ir["spec"]["nodes"]]
        assert "modifier.content" in types
        assert "transform.xslt" in types
        assert "script.groovy" in types


class TestBpmn2Parse:
    def test_parse_bpmn2_iflw(self) -> None:
        """Parse a BPMN2 .iflw file (SAP CPI native format)."""
        # Minimal BPMN2 with ifl extensions
        bpmn2_xml = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn2:definitions xmlns:bpmn2="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:ifl="http:///com.sap.ifl.model/Ifl.xsd">
  <bpmn2:collaboration id="Collab" name="Test Flow">
    <bpmn2:extensionElements>
      <ifl:SenderChannel>
        <ifl:Parameter name="url" value="/api"/>
      </ifl:SenderChannel>
      <ifl:ReceiverChannel>
        <ifl:Parameter name="url" value="https://backend.example.com"/>
      </ifl:ReceiverChannel>
      <ifl:Script>
        <ifl:Parameter name="language" value="Groovy"/>
      </ifl:Script>
    </bpmn2:extensionElements>
  </bpmn2:collaboration>
</bpmn2:definitions>"""
        parsed = parse_bpmn2_iflw(bpmn2_xml)
        assert parsed["name"] == "Test Flow"
        assert parsed["sender"] is not None
        assert parsed["receiver"] is not None
        assert len(parsed["steps"]) >= 1

    def test_parse_real_codejam_iflw(self) -> None:
        """Parse a real .iflw file from the SAP CodeJam repo."""
        codejam_zip = Path(
            "/tmp/sap-codejam/assets/cloud-integration/Request Employee Dependants - Cloud Connector.zip"
        )
        if not codejam_zip.is_file():
            pytest.skip("CodeJam ZIP not available")

        with zipfile.ZipFile(codejam_zip) as zf:
            iflw_files = [n for n in zf.namelist() if n.endswith(".iflw")]
            if not iflw_files:
                pytest.skip("No .iflw file in ZIP")
            content = zf.read(iflw_files[0])

        parsed = parse_bpmn2_iflw(content)
        # Should find at least sender or receiver
        assert parsed["sender"] is not None or parsed["receiver"] is not None or len(parsed["steps"]) > 0


class TestImportParserIntegration:
    def test_import_codejam_zip_with_enhanced_parser(self) -> None:
        """The enhanced import parser can process CodeJam ZIPs."""
        from oiw.compiler.import_parser import import_archive

        codejam_zip = Path(
            "/tmp/sap-codejam/assets/cloud-integration/Request Employee Dependants - Cloud Connector.zip"
        )
        if not codejam_zip.is_file():
            pytest.skip("CodeJam ZIP not available")

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            report = import_archive(Path(tmpdir), codejam_zip, "sap-cloud-integration-2026-07")
            # Should at least find some recognized components
            assert len(report.recognized) > 0 or report.status in ("PARTIAL", "FULL")
