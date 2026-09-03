"""Tenant absorption tests (Phase 2 EMG experience) — mock tenant only.

Covers: crawl→import→redact→persist→promote; content-hash dedup/resume;
customer-content license handling; insight/task shapes.
"""

from __future__ import annotations

import asyncio
import io
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.emg.promotion import MemoryPromotionState  # noqa: E402
from oiw.emg.store import JsonlEmgStore  # noqa: E402
from oiw.tenant.absorb import (  # noqa: E402
    ABSORB_PROVENANCE_SOURCE,
    absorb_tenant,
    flow_shape_from_ir,
    requirement_for_artifact,
)


def _fake_iflw_zip(
    flow_id: str = "TestFlow", steps: tuple[str, ...] = ("ContentModifier", "JsonToXmlConverter")
) -> bytes:
    """A minimal single-iFlow ZIP the import parser recognizes."""
    "".join(f"<ifl:property><key>activityType</key><value>{s}</value></ifl:property>" for s in steps)
    iflw = f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn2:definitions xmlns:bpmn2="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:ifl="http:///com.sap.ifl.model/Ifl.xsd" id="Definitions_1">
  <bpmn2:collaboration id="Collaboration_1">
    <bpmn2:messageFlow id="MessageFlow_1" name="HTTPS" sourceRef="Participant_1" targetRef="StartEvent_1">
      <bpmn2:extensionElements>
        <ifl:property><key>ComponentType</key><value>HTTPS</value></ifl:property>
        <ifl:property><key>direction</key><value>Sender</value></ifl:property>
        <ifl:property><key>urlPath</key><value>/{flow_id}</value></ifl:property>
      </bpmn2:extensionElements>
    </bpmn2:messageFlow>
  </bpmn2:collaboration>
  <bpmn2:process id="Process_1">
    <bpmn2:startEvent id="StartEvent_1"><bpmn2:messageEventDefinition/></bpmn2:startEvent>
    <bpmn2:callActivity id="CallActivity_1" name="step">
      <bpmn2:extensionElements>
        <ifl:property><key>activityType</key><value>{steps[0]}</value></ifl:property>
      </bpmn2:extensionElements>
    </bpmn2:callActivity>
    <bpmn2:callActivity id="CallActivity_2" name="step2">
      <bpmn2:extensionElements>
        <ifl:property><key>activityType</key><value>{steps[1] if len(steps) > 1 else steps[0]}</value></ifl:property>
      </bpmn2:extensionElements>
    </bpmn2:callActivity>
    <bpmn2:endEvent id="EndEvent_1"><bpmn2:messageEventDefinition/></bpmn2:endEvent>
  </bpmn2:process>
</bpmn2:definitions>
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"src/main/resources/scenarioflows/integrationflow/{flow_id}.iflw", iflw)
    return buf.getvalue()


def _mock_tenant(zips: dict[str, bytes]):
    """Build a MockTransport adapter serving packages/{artifacts}."""
    import httpx

    from oiw.tenant.sap_ci_adapter import SapCiTenantAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "GET" and "/IntegrationPackages" in url and "$count" not in url:
            results = [{"Id": pkg, "Name": pkg, "Version": "1.0.0", "Mode": "READ_ONLY"} for pkg in zips]
            return httpx.Response(200, json={"d": {"results": results}})
        if request.method == "GET" and "IntegrationDesigntimeArtifacts" in url and "$value" not in url:
            results = []
            for key, _blob in zips.items():
                pkg, art = key.split("/", 1)
                results.append(
                    {
                        "Id": art,
                        "Name": art,
                        "Version": "1.0.0",
                        "__metadata": {"media_src": f"https://example.invalid/api/v1/{pkg}('{art}')/$value"},
                    }
                )
            # crude per-package filter
            import re

            re.search(r"IntegrationDesigntimeArtifacts\(Id='([^']+)'", url) or re.search(
                r"IntegrationPackages\('([^']+)'\)", url
            )
            return httpx.Response(200, json={"d": {"results": results}})
        # $value download
        for key, blob in zips.items():
            pkg, art = key.split("/", 1)
            if url.endswith(f"{art}')/$value") or f"'{art}'" in url and "$value" in url:
                return httpx.Response(200, content=blob)
        return httpx.Response(200, content=next(iter(zips.values())))

    adapter = SapCiTenantAdapter(
        tenant_url="https://example.invalid/api/v1",
        username="u",
        password="p",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://example.invalid/api/v1"
        ),
    )
    from oiw.environments import AuthConfig, DeploymentPolicy, EnvironmentProfile

    profile = EnvironmentProfile(
        name="btp",
        target="sap-cloud-integration-2026-07",
        auth=AuthConfig(method="basic", credential_ref="test"),
        deployment_policy=DeploymentPolicy(requires_approval=False),
    )
    return adapter, profile


@pytest.fixture()
def store(tmp_path: Path) -> JsonlEmgStore:
    s = JsonlEmgStore(root=tmp_path / "emg", create_if_missing=True)
    s.load()
    return s


class TestAbsorbTenant:
    def test_absorbs_and_promotes(self, store, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        zips = {"PkgA/Flow1": _fake_iflw_zip("Flow1")}
        adapter, profile = _mock_tenant(zips)

        async def run():
            # absorb_tenant owns the connection lifecycle.
            return await absorb_tenant(
                adapter,
                store,
                max_artifacts=10,
                delay_s=0,
                corpus_dir=tmp_path / "corpus",
                progress=None,
            )

        stats = asyncio.run(run())
        assert stats.artifacts_pulled >= 1
        assert stats.insights_promoted >= 1
        records = store.list_insights(state=MemoryPromotionState.PROJECT_APPROVED)
        assert len(records) == 1
        rec = records[0]
        assert rec.insight.provenance.match_stage == ABSORB_PROVENANCE_SOURCE
        # Workflow carries the imported node types
        types = [n["action"][2] for n in rec.insight.successful_workflow]
        assert types  # non-empty chain
        # Task node persisted with organization scope + catalog provenance
        assert store.stats()["tasks"] >= 1

    def test_customer_content_license_never_apache(self, store, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        zips = {"PkgA/Flow2": _fake_iflw_zip("Flow2")}
        adapter, profile = _mock_tenant(zips)

        async def run():
            # absorb_tenant owns the connection lifecycle.
            return await absorb_tenant(
                adapter,
                store,
                max_artifacts=10,
                delay_s=0,
                corpus_dir=tmp_path / "corpus",
                progress=None,
            )

        asyncio.run(run())
        meta_files = list((tmp_path / "corpus").glob("*/metadata.yaml"))
        assert meta_files, "absorption wrote no metadata"
        meta = yaml.safe_load(meta_files[0].read_text())
        assert meta["license"] == "customer-content"
        assert meta["redacted"] is True
        assert meta["provenance"]["source"] == ABSORB_PROVENANCE_SOURCE

    def test_dedup_skips_unchanged_artifacts(self, store, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        zips = {"PkgA/Flow3": _fake_iflw_zip("Flow3")}
        adapter, profile = _mock_tenant(zips)

        async def run_all():
            # Pre-connect: absorb_tenant then reuses the injected transport
            # for BOTH crawls (its owns-connection lifecycle only applies to
            # adapters it had to connect itself).
            await adapter.connect(profile)
            try:
                first = await absorb_tenant(
                    adapter,
                    store,
                    max_artifacts=10,
                    delay_s=0,
                    corpus_dir=tmp_path / "corpus",
                    progress=None,
                )
                second = await absorb_tenant(
                    adapter,
                    store,
                    max_artifacts=10,
                    delay_s=0,
                    corpus_dir=tmp_path / "corpus",
                    progress=None,
                )
                return first, second
            finally:
                await adapter.disconnect()

        _, stats2 = asyncio.run(run_all())
        # Second run over unchanged content: pulled but deduped, no new insights
        assert stats2.artifacts_deduped >= 1
        assert stats2.insights_promoted == 0
        assert store.stats()["insights"] == 1


class TestShapes:
    def test_flow_shape_orders_from_entrypoint(self) -> None:
        ir = {
            "spec": {
                "entrypoints": [{"id": "s", "type": "sender.http"}],
                "nodes": [
                    {"id": "b", "type": "log.message"},
                    {"id": "a", "type": "modifier.content"},
                ],
                "edges": [
                    {"from": "s", "to": "a"},
                    {"from": "a", "to": "b"},
                ],
            }
        }
        shape = flow_shape_from_ir(ir)
        assert [n["action"][3] for n in shape] == ["s", "a", "b"]
        assert [n["action"][2] for n in shape] == ["sender.http", "modifier.content", "log.message"]

    def test_requirement_carries_components_and_archetype(self) -> None:
        ir = {
            "spec": {
                "entrypoints": [{"id": "s", "type": "sender.http"}],
                "nodes": [{"id": "r", "type": "receiver.http"}],
                "edges": [{"from": "s", "to": "r"}],
            }
        }
        req = requirement_for_artifact("P", "F", ir)
        assert req.archetype == "http-to-http"
        assert "receiver.http" in req.components
        assert req.confidence == 0.8


def _fake_iflw_servicetask_zip(
    flow_id: str = "FlowWithServiceTask",
    activity_type: str | None = "ExternalCall",
    task_name: str = "Request-Reply",
) -> bytes:
    """Generate a synthetic .iflw ZIP containing a serviceTask."""
    ext_props = ""
    if activity_type:
        ext_props = f"""
      <bpmn2:extensionElements>
        <ifl:property><key>activityType</key><value>{activity_type}</value></ifl:property>
        <ifl:property><key>cmdVariantUri</key><value>ctype::FlowstepVariant/cname::{activity_type}/version::1.0.4</value></ifl:property>
      </bpmn2:extensionElements>"""
    iflw = f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn2:definitions xmlns:bpmn2="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:ifl="http:///com.sap.ifl.model/Ifl.xsd" id="Definitions_1">
  <bpmn2:collaboration id="Collaboration_1">
    <bpmn2:messageFlow id="MessageFlow_1" name="HTTPS" sourceRef="Participant_1" targetRef="StartEvent_1">
      <bpmn2:extensionElements>
        <ifl:property><key>ComponentType</key><value>HTTPS</value></ifl:property>
        <ifl:property><key>direction</key><value>Sender</value></ifl:property>
        <ifl:property><key>urlPath</key><value>/{flow_id}</value></ifl:property>
      </bpmn2:extensionElements>
    </bpmn2:messageFlow>
    <bpmn2:messageFlow id="MessageFlow_2" name="HTTP_Receiver" sourceRef="EndEvent_1" targetRef="Participant_2">
      <bpmn2:extensionElements>
        <ifl:property><key>ComponentType</key><value>HTTP</value></ifl:property>
        <ifl:property><key>direction</key><value>Receiver</value></ifl:property>
      </bpmn2:extensionElements>
    </bpmn2:messageFlow>
  </bpmn2:collaboration>
  <bpmn2:process id="Process_1">
    <bpmn2:startEvent id="StartEvent_1"><bpmn2:messageEventDefinition/></bpmn2:startEvent>
    <bpmn2:callActivity id="CallActivity_1" name="modifier">
      <bpmn2:extensionElements>
        <ifl:property><key>activityType</key><value>Enricher</value></ifl:property>
      </bpmn2:extensionElements>
    </bpmn2:callActivity>
    <bpmn2:serviceTask id="ServiceTask_1" name="{task_name}">{ext_props}
    </bpmn2:serviceTask>
    <bpmn2:endEvent id="EndEvent_1"><bpmn2:messageEventDefinition/></bpmn2:endEvent>
  </bpmn2:process>
</bpmn2:definitions>
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"src/main/resources/scenarioflows/integrationflow/{flow_id}.iflw", iflw)
    return buf.getvalue()


class TestServiceTaskClassification:
    """WP-10 H9: Absorb ServiceTask classification (thread #5's other half)."""

    def test_external_call_classified_as_receiver_http(self, tmp_path: Path) -> None:
        from oiw.tenant.absorb import _ir_from_zip

        zip_bytes = _fake_iflw_servicetask_zip(activity_type="ExternalCall")
        zip_path = tmp_path / "external_call.zip"
        zip_path.write_bytes(zip_bytes)

        ir = _ir_from_zip(zip_path, "external-call-artifact")
        assert ir is not None
        st_node = next(n for n in ir["spec"]["nodes"] if n["id"] == "ServiceTask_1")
        # Must produce receiver.http instead of an unclassified stub
        assert st_node["type"] == "receiver.http"

    def test_non_external_call_service_task_stays_unclassified(self, tmp_path: Path) -> None:
        from oiw.tenant.absorb import _ir_from_zip

        zip_bytes = _fake_iflw_servicetask_zip(activity_type="CustomTask", task_name="custom_op")
        zip_path = tmp_path / "non_external_call.zip"
        zip_path.write_bytes(zip_bytes)

        ir = _ir_from_zip(zip_path, "non-external-call-artifact")
        assert ir is not None
        st_node = next(n for n in ir["spec"]["nodes"] if n["id"] == "ServiceTask_1")
        # Honest: stays unclassified ServiceTask
        assert st_node["type"] == "ServiceTask"

    def test_turbo_injection_boundary_oiw_i002(self, tmp_path: Path) -> None:
        """Boundary test: reclassified chain is fully piece-covered and does NOT
        trip OIW-I002; unclassified ServiceTask chain still trips OIW-I002."""
        from oiw.agent.turbo import _assembly_from_injection, _injection_is_shippable
        from oiw.tenant.absorb import _ir_from_zip, flow_shape_from_ir

        # 1. Chain with ExternalCall -> classifies as receiver.http
        zip_ext = tmp_path / "ext.zip"
        zip_ext.write_bytes(_fake_iflw_servicetask_zip(activity_type="ExternalCall"))
        ir_ext = _ir_from_zip(zip_ext, "ext-flow")
        shape_ext = flow_shape_from_ir(ir_ext)

        injected_ext = [
            {
                "action": "flow.patch",
                "arguments": {
                    "operations": [{"op": "addNode", "node": {"id": s["action"][3], "type": s["action"][2]}}]
                },
            }
            for s in shape_ext
        ]
        assembly_ext = _assembly_from_injection(injected_ext)
        assert assembly_ext is not None
        # Should be shippable (all pieces proven) -> NO OIW-I002
        assert _injection_is_shippable(assembly_ext) is True

        # 2. Chain with non-ExternalCall -> stays ServiceTask
        zip_non_ext = tmp_path / "non_ext.zip"
        zip_non_ext.write_bytes(_fake_iflw_servicetask_zip(activity_type="UnknownServiceTask", task_name="op"))
        ir_non_ext = _ir_from_zip(zip_non_ext, "non-ext-flow")
        shape_non_ext = flow_shape_from_ir(ir_non_ext)

        injected_non_ext = [
            {
                "action": "flow.patch",
                "arguments": {
                    "operations": [{"op": "addNode", "node": {"id": s["action"][3], "type": s["action"][2]}}]
                },
            }
            for s in shape_non_ext
        ]
        assembly_non_ext = _assembly_from_injection(injected_non_ext)
        assert assembly_non_ext is not None
        # Contains unclassified ServiceTask -> NOT shippable -> trips OIW-I002 fallback
        assert _injection_is_shippable(assembly_non_ext) is False

