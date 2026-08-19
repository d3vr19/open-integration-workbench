#!/usr/bin/env python3
"""Tenant smoke test (WP-08 Track 0, T0-002 acceptance).

Manual — NOT run in CI. Verifies that SapCiTenantAdapter works against a
real SAP Cloud Integration tenant with the credentials in the environment.

Usage:
    export OIW_USE_REAL_TENANT=1
    export OIW_TENANT_URL=https://<tenant>.it-cpi0XX.cfapps.<region>.hana.ondemand.com/api/v1
    export OIW_TENANT_USER=S0026012658
    export OIW_TENANT_PASSWORD='...'
    python scripts/tenant_smoke.py

Equivalent to:  oiw tenant ping --profile btp --project examples/order-to-s4
                oiw tenant list --top 5 --profile btp --project examples/order-to-s4
                oiw tenant artifacts --package <first-pkg-id> --profile btp ...
                oiw tenant pull   --package <first-pkg-id> --out /tmp/smoke.zip --profile btp ...

Acceptance (WP-08 T0-002):
    - ≥ 1 package listed from the tenant
    - At least 1 artifact visible inside that package
    - The first artifact's $value downloads as a non-empty ZIP

Per WP-08 §C-004: this script does NOT upload, deploy, or mutate tenant
content. It is read-only.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Allow running from a checkout without `pip install -e .`
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.environments import load_profile  # noqa: E402
from oiw.tenant import SapCiTenantError, build_tenant_adapter  # noqa: E402

EXAMPLE_PROJECT = REPO_ROOT / "examples" / "order-to-s4"


async def smoke() -> int:
    required = ("OIW_TENANT_URL", "OIW_TENANT_USER", "OIW_TENANT_PASSWORD")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"FAIL: missing env vars: {', '.join(missing)}", file=sys.stderr)
        print("See .env.example (WP-08 Track 0 section).", file=sys.stderr)
        return 2
    if os.environ.get("OIW_USE_REAL_TENANT", "").strip() not in {"1", "true", "True", "yes"}:
        print("FAIL: OIW_USE_REAL_TENANT is not '1'. Set it to opt into the real adapter.", file=sys.stderr)
        return 2

    prof = load_profile(EXAMPLE_PROJECT, "btp")
    adapter = build_tenant_adapter()
    print(f"Adapter type: {type(adapter).__name__}")
    if type(adapter).__name__ != "SapCiTenantAdapter":
        print(f"FAIL: expected SapCiTenantAdapter, got {type(adapter).__name__}", file=sys.stderr)
        return 1

    print(f"Connecting to {os.environ['OIW_TENANT_URL']} ...")
    try:
        await adapter.connect(prof)
    except SapCiTenantError as exc:
        print(f"FAIL: connect() raised: {exc}", file=sys.stderr)
        return 1
    print("OK: connected (Basic auth accepted by tenant)")

    # 1. List packages
    pkgs = await adapter.list_packages(top=5)
    print(f"\n[1] Packages listed: {len(pkgs)} (top=5)")
    for p in pkgs:
        print(f"    - id={p.id}  name={p.name}  mode={p.mode}")
    if not pkgs:
        print("FAIL: tenant returned 0 packages (expected ≥ 1)", file=sys.stderr)
        await adapter.disconnect()
        return 1

    # 2. List artifacts in the first package
    first_pkg = pkgs[0].id
    arts = await adapter.list_artifacts(first_pkg, top=10)
    print(f"\n[2] Artifacts in '{first_pkg}': {len(arts)} (top=10)")
    for a in arts[:5]:
        print(f"    - id={a.id}  version={a.version}")
    if not arts:
        print("FAIL: package has no artifacts (expected ≥ 1)", file=sys.stderr)
        await adapter.disconnect()
        return 1

    # 3. Download the first artifact
    target = arts[0]
    blob = await adapter.download_artifact(target.id, target.version)
    print(f"\n[3] Downloaded {target.id} v{target.version}: {len(blob)} bytes")
    if len(blob) < 4 or blob[:2] != b"PK":
        print(f"FAIL: downloaded content is not a ZIP (first 4 bytes: {blob[:4]!r})", file=sys.stderr)
        await adapter.disconnect()
        return 1
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
        tf.write(blob)
        print(f"    wrote: {tf.name}")

    await adapter.disconnect()
    print("\nALL SMOKE CHECKS PASSED — WP-08 T0-002 acceptance met.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(smoke()))
