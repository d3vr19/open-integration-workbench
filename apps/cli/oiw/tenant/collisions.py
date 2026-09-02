"""Endpoint-collision preflight (hardening guard #1).

Lesson (2x live, 2026-08-26): HTTPS entrypoint paths are TENANT-GLOBAL.
Deploying content whose sender path is already bound by another STARTED
flow produces a runtime ERROR indistinguishable from a content failure —
it cost a day of bisection once already.

`find_path_collisions()` pulls every designtime bundle in the target
package, extracts each flow's HTTPS sender path, and reports who else
claims the path we are about to deploy. Read-only; uses proven verbs.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

from .sap_ci_adapter import SapCiTenantAdapter, SapCiTenantError


@dataclass
class PathClaim:
    artifact_id: str
    version: str
    path: str


def extract_https_paths(iflw_xml: str) -> list[str]:
    """All urlPath values from HTTPS-sender messageFlows in one .iflw."""
    paths: list[str] = []
    for m in re.finditer(r"<key>urlPath</key>\s*<value>([^<]*)</value>", iflw_xml):
        value = m.group(1).strip()
        if value:
            paths.append(value if value.startswith("/") else f"/{value}")
    return paths


async def collect_package_path_claims(adapter: SapCiTenantAdapter, package_id: str) -> list[PathClaim]:
    """Download every designtime bundle in the package; return path claims."""
    claims: list[PathClaim] = []
    artifacts = await adapter.list_artifacts(package_id, top=100)
    for art in artifacts:
        try:
            blob = await adapter.download_artifact(art.id, art.version)
        except SapCiTenantError:
            continue  # unreadable artifact — not our collision problem
        zf = zipfile.ZipFile(io.BytesIO(blob))
        for name in zf.namelist():
            if name.endswith(".iflw"):
                xml = zf.read(name).decode("utf-8", errors="replace")
                for p in extract_https_paths(xml):
                    claims.append(PathClaim(art.id, art.version, p))
                break
    return claims


def find_collisions(claims: list[PathClaim], desired_path: str, exclude_artifact_id: str) -> list[PathClaim]:
    """Other artifacts claiming `desired_path`, excluding the deploy target."""
    want = desired_path.rstrip("/") or "/"
    out = []
    for c in claims:
        if c.artifact_id == exclude_artifact_id:
            continue
        if c.path.rstrip("/") == want:
            out.append(c)
    return out
