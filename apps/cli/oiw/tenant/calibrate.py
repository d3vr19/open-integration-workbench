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
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from ..compiler.sap_export import build_cpi_bundle, cpi_bundle_identity
from ..environments import EnvironmentProfile
from .sap_ci_adapter import SapCiTenantAdapter, SapCiTenantError


def _epoch_ms(iso_started_at: str) -> float:
    """Parse the report's startedAt ISO timestamp to epoch ms."""
    try:
        ts = datetime.fromisoformat(iso_started_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ts.timestamp() * 1000.0
    except (ValueError, TypeError):
        return 0.0


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
    display_name: str | None = None,
) -> tuple[str, str | None]:
    """Poll /IntegrationRuntimeArtifacts until terminal. Returns (status, raw).

    LIVE LAWS (2026-09-03, TestOIW/oiw-wlog):
      1. The runtime row's `Name` is the artifact's DISPLAY name, not its
         Id — create-with-human-display-name deploys fine but polls by Id
         as TIMEOUT.
      2. The gateway's $filter REJECTS spaces inside string literals
         (single-variable probes: eq/startswith/contains all 400 on
         multi-word names). Spaced names are matched CLIENT-SIDE: pull
         the most recent runtime rows (ordered desc) and compare locally.
    """
    deadline = asyncio.get_event_loop().time() + timeout_s
    last = "UNKNOWN"
    candidates = [artifact_id]
    if display_name and display_name != artifact_id:
        candidates.append(display_name)
    spaced = any(" " in c for c in candidates)
    while asyncio.get_event_loop().time() < deadline:
        if spaced:
            r = await client.get(
                "/IntegrationRuntimeArtifacts",
                params={
                    "$orderby": "DeployedOn desc",
                    "$top": 50,
                    "$format": "json",
                },
                headers={**auth, "Accept": "application/json"},
            )
            results = []
            if "json" in r.headers.get("content-type", ""):
                results = [
                    a
                    for a in r.json().get("d", {}).get("results", [])
                    if a.get("Name") in candidates
                ]
        else:
            results = []
            for name in candidates:
                r = await client.get(
                    "/IntegrationRuntimeArtifacts",
                    params={
                        "$filter": f"Name eq '{name}'",
                        "$orderby": "DeployedOn desc",
                        "$top": 1,
                        "$format": "json",
                    },
                    headers={**auth, "Accept": "application/json"},
                )
                if "json" in r.headers.get("content-type", ""):
                    results.extend(r.json().get("d", {}).get("results", []))
        if results:
            raw = str(results[0].get("Status") or "").upper()
            last = {"STARTED": "STARTED", "ERROR": "ERROR", "DEPLOYED": "STARTED"}.get(
                raw, "PENDING"
            )
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
    create: bool = False,
) -> CalibrationReport:
    """Run the full oracle loop for one allowlisted target in `package_id`.

    `create=True` (P6 autonomous-creation path): the artifact must NOT
    exist yet — POST-entity CREATE (adapter.create_artifact), fresh
    identity (no inheritance), then the same deploy→poll→message→MPL
    oracle loop. Still allowlist-gated + scratch-package-only.
    """
    rep = CalibrationReport(package_id=package_id, artifact_id="")
    rep.started_at = datetime.now(tz=UTC).isoformat()

    flows = sorted((project_path / "flows").rglob("flow.yaml"))
    if len(flows) != 1:
        raise SapCiTenantError(f"calibrate expects exactly one flow, found {len(flows)}")
    flow = yaml.safe_load(flows[0].read_text(encoding="utf-8"))

    symbolic = iflw_name = bundle_name = None
    ext_configs: list[dict[str, str]] = []
    await adapter.connect(profile)
    try:
        if create:
            if not artifact_id:
                raise SapCiTenantError("create mode requires an explicit --artifact id")
            rep.artifact_id = artifact_id
            # Fresh identity: the new bundle's SymbolicName is its own id.
            symbolic = artifact_id
            iflw_name = None
            bundle_name = display_name or artifact_id
            # Path-collision preflight still applies (package-level; paths
            # are tenant-global — turbo derives unique /<artifact-id> paths
            # so package-level is the fast sufficient check for scratch).
            entry0 = flow["spec"]["entrypoints"][0]
            if entry0.get("type") == "sender.http":
                from .collisions import collect_package_path_claims, find_collisions

                desired = str((entry0.get("config") or {}).get("path", "/"))
                try:
                    claims = await collect_package_path_claims(adapter, package_id)
                except SapCiTenantError:
                    claims = []  # nav wedge — create-mode paths are compiler-unique
                hits = find_collisions(claims, desired, exclude_artifact_id=artifact_id)
                if hits:
                    raise SapCiTenantError(
                        f"endpoint collision: path {desired!r} is already claimed by "
                        + ", ".join(f"{h.artifact_id} ({h.version})" for h in hits)
                        + " — pick a different entrypoint path"
                    )
            archive, _digest = build_cpi_bundle(
                flow,
                symbolic_name=symbolic,
                iflw_name=iflw_name,
                display_name=bundle_name,
                project_root=project_path,
                configurations_out=ext_configs,
            )
            result = await adapter.create_artifact(package_id, artifact_id, bundle_name, archive)
            rep.uploaded_ok = bool(result.success)
            if not result.success:
                rep.error_detail = result.error
                return rep
            target_version = result.version or "1.0.0"  # tenant auto-generates
        else:
            target = await adapter._resolve_target_with_fallback(package_id, artifact_id)
            existing = await adapter.download_artifact(target.id, target.version)
            symbolic, iflw_name, bundle_name = cpi_bundle_identity(existing)
            rep.artifact_id = target.id

            # Endpoint-collision preflight: paths are tenant-global; deploying a
            # path bound by ANOTHER flow yields a runtime ERROR that looks
            # exactly like a content failure (2x live lesson, p5-p6-plan.md §6).
            # During a gateway nav-wedge the package walk 404s; the preflight
            # degrades LOUDLY (warning in the report) instead of aborting —
            # scratch artifacts carry compiler-derived unique paths.
            entry0 = flow["spec"]["entrypoints"][0]
            if entry0.get("type") == "sender.http":
                from .collisions import collect_package_path_claims, find_collisions

                desired = str((entry0.get("config") or {}).get("path", "/"))
                try:
                    claims = await collect_package_path_claims(adapter, package_id)
                except SapCiTenantError:
                    claims = []
                    rep.error_detail = (
                        (rep.error_detail + " | " if rep.error_detail else "")
                        + "collision preflight skipped: package nav unavailable (gateway cooldown)"
                    )
                hits = find_collisions(claims, desired, exclude_artifact_id=target.id)
                if hits:
                    raise SapCiTenantError(
                        f"endpoint collision: path {desired!r} is already claimed by "
                        + ", ".join(f"{h.artifact_id} ({h.version})" for h in hits)
                        + " — pick a different entrypoint path"
                    )

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
                configurations_out=ext_configs,
            )
            result = await adapter.upload_package(
                package_id, archive, "sha256:calibrate", artifact_id=artifact_id
            )
            rep.uploaded_ok = bool(result.success)
            if not result.success:
                rep.error_detail = result.error
                return rep
            target_version = target.version

        # Externalized-param note (terminal-HTTP receiver law, 2026-09-02):
        # the bundle's parameters.prop carries the literal values; the
        # tenant AUTO-CREATES the artifact Configuration rows from it on
        # upload (live-proven: oiw_turbo_fwdUrl appeared without any POST).
        # The Configurations nav is read-only via API (POST=501) — values
        # flow exclusively through the bundle. No explicit deploy needed.

        deploy_result = await adapter.deploy(package_id, target_version, artifact_id=artifact_id)
        rep.deploy_accepted = bool(deploy_result.success)

        status, raw = await _poll_terminal(
            adapter._client,
            adapter._basic_auth_header(),
            rep.artifact_id,
            timeout_s=timeout_s,
            display_name=display_name or bundle_name,
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
            # MPL rows key on IntegrationFlowName — which follows the
            # DISPLAY name on this tenant (same law as the runtime poll).
            mpl_names = [rep.artifact_id]
            dname = display_name or bundle_name
            if dname and dname != rep.artifact_id:
                mpl_names.append(dname)
            mpl_rows: list[dict[str, Any]] = []
            # gateway $filter rejects spaces in literals (live law, 2026-09-03):
            # spaced names are pulled unfiltered (recent, top N) and matched
            # client-side; plain names use the exact server filter.
            if any(" " in nm for nm in mpl_names):
                mpl = await adapter._client.get(
                    "/MessageProcessingLogs",
                    params={
                        "$orderby": "LogStart desc",
                        "$top": 50,
                        "$format": "json",
                    },
                    headers={**adapter._basic_auth_header(), "Accept": "application/json"},
                )
                if "json" in mpl.headers.get("content-type", ""):
                    mpl_rows = [
                        row
                        for row in mpl.json().get("d", {}).get("results", [])
                        if row.get("IntegrationFlowName") in mpl_names
                    ]
            else:
                for nm in mpl_names:
                    mpl = await adapter._client.get(
                        "/MessageProcessingLogs",
                        params={
                            "$filter": f"IntegrationFlowName eq '{nm}'",
                            "$orderby": "LogStart desc",
                            "$top": 5,
                            "$format": "json",
                        },
                        headers={**adapter._basic_auth_header(), "Accept": "application/json"},
                    )
                    if "json" in mpl.headers.get("content-type", ""):
                        mpl_rows.extend(mpl.json().get("d", {}).get("results", []))
                    if mpl_rows:
                        break
            if mpl_rows:
                # MPL EPOCH FILTER (2026-09-02): only rows from THIS run's
                # window count. An artifact redeployed many times (bisection
                # history) carries stale FAILED rows that poison the verdict
                # — LogStart is /Date(<epoch_ms>)/, older rows are dropped.
                epoch_ms = _epoch_ms(rep.started_at)

                def _row_logstart_ms(row: dict[str, Any]) -> float | None:
                    raw = str(row.get("LogStart") or "")
                    m = re.search(r"\((\d+)\)", raw)
                    return float(m.group(1)) if m else None

                rep.mpl_rows = [
                    {
                        k: row.get(k)
                        for k in ("MessageGuid", "Status", "CustomStatus", "IntegrationFlowName", "LogStart")
                    }
                    for row in mpl_rows
                    # keep rows at/after this run started (1s clock-skew slack)
                    if (t := _row_logstart_ms(row)) is None or t >= epoch_ms - 1000.0
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
