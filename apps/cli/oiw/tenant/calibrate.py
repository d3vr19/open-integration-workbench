"""Tenant oracle harness (P5a-M1) — calibrate local expectations vs reality.

`oiw tenant calibrate` runs the full loop against ONE pinned artifact:

    export CPI bundle -> upload (PUT entity) -> deploy (function import)
    -> poll runtime status -> [if STARTED] send a test message to the
    flow's HTTPS endpoint -> pull MPL rows + error info -> report YAML

Everything is policy-gated like the rest of the write path (allowlist +
pinning required; scratch packages only; never CI).

Findings baked in (2026-08-26, live):
    - LogFiles endpoint returns 501 on CF tenants (server logs unavailable)
    - RuntimeArtifactErrorInformations exists in the edmx but is NOT served
      ("could not find entity set") — startup-failure detail must be
      obtained by bundle bisection instead.
    - Message ingress (/http/<path>) lives on the RUNTIME host (landscape
      segment with '-rt' suffix); the designtime host returns 403.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from ..compiler.sap_export import build_cpi_bundle, cpi_bundle_identity
from ..environments import EnvironmentProfile
from .sap_ci_adapter import SapCiTenantAdapter, SapCiTenantError


def runtime_base_url(tenant_url: str) -> str:
    """Derive the CPI RUNTIME base URL from the designtime tenant URL.

    Runtime-facing endpoints (/http/<path> message ingress) live on a host
    whose landscape segment carries an '-rt' suffix; reusing the designtime
    host returns HTTP 403 (live finding, 2026-08-26):

        designtime: https://<tenant>.it-cpi021.cfapps.<region>.hana.ondemand.com
        runtime:    https://<tenant>.it-cpi021-rt.cfapps.<region>.hana.ondemand.com

    OIW_TENANT_RUNTIME_URL overrides outright for non-CF landscapes.
    """
    override = os.environ.get("OIW_TENANT_RUNTIME_URL", "").strip()
    if override:
        return override.rstrip("/")
    base = tenant_url.split("/api/v1")[0].rstrip("/")
    scheme, _, rest = base.partition("://")
    host = rest.split("/")[0]
    if "-rt." in host or host.endswith("-rt"):
        return f"{scheme}://{host}"
    if ".cfapps" in host:
        head, tail = host.split(".cfapps", 1)
        host = f"{head}-rt.cfapps{tail}"
    return f"{scheme}://{host}"


def message_method(entrypoint: dict) -> str:
    """HTTP verb for exercising the entrypoint: honor its declared methods."""
    cfg = entrypoint.get("config") or {}
    methods = [str(m).upper() for m in (cfg.get("methods") or ["POST"])]
    return "GET" if "GET" in methods else methods[0]


@dataclass
class CalibrationReport:
    """Ground-truth verdict of the tenant for one artifact."""

    package_id: str
    artifact_id: str
    uploaded_ok: bool = False
    deploy_accepted: bool = False
    tracking_uuid: str | None = None
    final_status: str = "UNKNOWN"  # STARTED | ERROR | TIMEOUT | ...
    error_detail: str | None = None
    message_sent: bool = False
    http_response_status: int | None = None
    mpl_rows: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibration": {
                "packageId": self.package_id,
                "artifactId": self.artifact_id,
                "uploadedOk": self.uploaded_ok,
                "deployAccepted": self.deploy_accepted,
                "trackingUuid": self.tracking_uuid,
                "finalStatus": self.final_status,
                "errorDetail": self.error_detail,
                "messageSent": self.message_sent,
                "httpResponseStatus": self.http_response_status,
                "mplRows": self.mpl_rows[:10],
                "startedAt": self.started_at,
                "finishedAt": self.finished_at,
            }
        }


async def _poll_terminal(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    artifact_id: str,
    timeout_s: int = 60,
    interval_s: int = 4,
) -> tuple[str, str | None]:
    """Poll /IntegrationRuntimeArtifacts until terminal. Returns (status, raw)."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    last = "UNKNOWN"
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(
            "/IntegrationRuntimeArtifacts",
            params={
                "$filter": f"Name eq '{artifact_id}'",
                "$orderby": "DeployedOn desc",
                "$top": 1,
                "$format": "json",
            },
            headers={**auth, "Accept": "application/json"},
        )
        if "json" in r.headers.get("content-type", ""):
            results = r.json().get("d", {}).get("results", [])
            if results:
                raw = str(results[0].get("Status") or "").upper()
                last = {"STARTED": "STARTED", "ERROR": "ERROR", "DEPLOYED": "STARTED"}.get(raw, "PENDING")
                if last in ("STARTED", "ERROR"):
                    return last, raw
        await asyncio.sleep(interval_s)
    return "TIMEOUT", last


async def calibrate_artifact(
    project_path: Path,
    profile: EnvironmentProfile,
    adapter: SapCiTenantAdapter,
    package_id: str,
    *,
    artifact_id: str | None = None,
    display_name: str | None = None,
    message_body: str = "{}",
    timeout_s: int = 60,
) -> CalibrationReport:
    """Run the full oracle loop for one allowlisted target in `package_id`."""
    rep = CalibrationReport(package_id=package_id, artifact_id="")
    rep.started_at = datetime.now(tz=UTC).isoformat()

    flows = sorted((project_path / "flows").rglob("flow.yaml"))
    if len(flows) != 1:
        raise SapCiTenantError(f"calibrate expects exactly one flow, found {len(flows)}")
    flow = yaml.safe_load(flows[0].read_text(encoding="utf-8"))

    # Identity inheritance (download current bundle first)
    symbolic = iflw_name = bundle_name = None
    await adapter.connect(profile)
    try:
        target = await adapter._resolve_target_artifact(package_id, artifact_id)
        existing = await adapter.download_artifact(target.id, target.version)
        symbolic, iflw_name, bundle_name = cpi_bundle_identity(existing)
        rep.artifact_id = target.id
        # Pre-upload backup (reversibility)
        bdir = project_path / ".oiw" / "tenant-cache"
        bdir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
        (bdir / f"backup-{package_id}-{target.id}-{stamp}.zip").write_bytes(existing)

        archive, _digest = build_cpi_bundle(
            flow,
            symbolic_name=symbolic,
            iflw_name=iflw_name,
            display_name=display_name or bundle_name or target.id,
            project_root=project_path,
        )
        result = await adapter.upload_package(
            package_id, archive, "sha256:calibrate", artifact_id=artifact_id
        )
        rep.uploaded_ok = bool(result.success)
        if not result.success:
            rep.error_detail = result.error
            return rep

        deploy_result = await adapter.deploy(package_id, target.version, artifact_id=artifact_id)
        rep.deploy_accepted = bool(deploy_result.success)

        status, raw = await _poll_terminal(
            adapter._client, adapter._basic_auth_header(), target.id, timeout_s=timeout_s
        )
        rep.final_status = status
        if raw == "ERROR":
            rep.error_detail = (
                "runtime start failed; SAP exposes no API-side startup log "
                "(LogFiles=501, RuntimeArtifactErrorInformations not served). "
                "Use bundle bisection: drop steps until STARTED."
            )

        # If started, exercise the HTTP entrypoint and pull MPL evidence.
        # ProcessDirect (and other non-HTTP) entrypoints have no runtime
        # HTTP endpoint — their verdict arrives via the CALLER's chain.
        if status == "STARTED" and flow["spec"]["entrypoints"][0].get("type") == "sender.http":
            entry = flow["spec"]["entrypoints"][0]
            path = str((entry.get("config") or {}).get("path", "/")).lstrip("/")
            # Message ingress lives on the RUNTIME host (-rt), NOT the
            # designtime host (403 there).
            host = runtime_base_url(str(adapter.tenant_url))
            method = message_method(entry)
            kwargs: dict[str, Any] = {
                "headers": {
                    **adapter._basic_auth_header(),
                    "Content-Type": "application/json",
                }
            }
            if method not in ("GET", "HEAD"):
                kwargs["content"] = message_body.encode()
            try:
                mr = await adapter._client.request(method, f"{host}/http/{path}", **kwargs)
                rep.message_sent = True
                rep.http_response_status = mr.status_code
            except httpx.HTTPError as exc:
                rep.error_detail = f"message send failed: {exc}"
            await asyncio.sleep(3)
            mpl = await adapter._client.get(
                "/MessageProcessingLogs",
                params={
                    "$filter": f"IntegrationFlowName eq '{target.id}'",
                    "$orderby": "LogStart desc",
                    "$top": 5,
                    "$format": "json",
                },
                headers={**adapter._basic_auth_header(), "Accept": "application/json"},
            )
            if "json" in mpl.headers.get("content-type", ""):
                rep.mpl_rows = [
                    {
                        k: row.get(k)
                        for k in ("MessageGuid", "Status", "CustomStatus", "IntegrationFlowName", "LogStart")
                    }
                    for row in mpl.json().get("d", {}).get("results", [])
                ]
        return rep
    finally:
        await adapter.disconnect()


def write_report(report: CalibrationReport, out: Path | None = None) -> Path:
    from .oracle_feedback import reward_from_calibration, reward_section

    path = out or Path(".oiw") / f"calibration-{report.artifact_id or 'unknown'}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    payload.update(reward_section(reward_from_calibration(report)))
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


__all__ = [
    "CalibrationReport",
    "calibrate_artifact",
    "message_method",
    "runtime_base_url",
    "write_report",
]
