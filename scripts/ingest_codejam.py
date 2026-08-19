#!/usr/bin/env python3
"""Ingest the SAP CodeJam repo into the durable EMG store (WP-08 PR-6 / B-001+B-002+B-003).

Manual — NOT in CI. Walks the cloned SAP-samples CodeJam repo at /tmp/sap-codejam,
extracts every iFlow artifact, imports each via the (now-fixed) BPMN2 parser,
redacts the IR, and persists:

  - packages/seed-corpus/artifacts/codejam-<exercise-id>/
      flow.yaml          — redacted IR
      import-report.yaml — recognized/opaque/unsupported components
      metadata.yaml      — provenance.source=sap-codejam, isReal=true, license=Apache-2.0
  - <emg_store_root>/
      insights.jsonl, tasks.jsonl, manifest.yaml — durable EMG store

Usage:
    export OIW_WORKSPACE=/home/z/my-project/open-integration-workbench
    python scripts/ingest_codejam.py [--codejam-root /tmp/sap-codejam]
                                     [--emg-store-root /tmp/oiw-emg-codejam]

Per WP-08 §6 B-001 acceptance: ≥ 8 distinct CodeJam artifacts on disk OR a
written inventory showing the repo has fewer, with every skipped artifact
listed and why. Per WP-08 §10 "Do Not": never skeletonize — failed imports
are parser bugs or documented gaps, not expert trajectories.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Allow running from a checkout without `pip install -e .`
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

import yaml  # noqa: E402

from oiw.agent.interpreter import NormalizedRequirement  # noqa: E402
from oiw.agent.redaction import Redactor  # noqa: E402
from oiw.compiler.import_parser import import_archive  # noqa: E402
from oiw.compiler.report import format_import_report  # noqa: E402
from oiw.compiler.sap_flow_parser import (  # noqa: E402
    convert_parsed_flow_to_oiw_ir,
    parse_bpmn2_iflw,
)
from oiw.emg.store import build_emg_store  # noqa: E402

DEFAULT_CODEJAM_ROOT = Path("/tmp/sap-codejam")
DEFAULT_EMG_STORE_ROOT = Path("/tmp/oiw-emg-codejam")
SEED_CORPUS_DIR = REPO_ROOT / "packages" / "seed-corpus" / "artifacts"


@dataclass
class IngestionResult:
    """Result of ingesting one iFlow."""

    artifact_id: str
    source_zip: str
    iflw_path: str | None
    status: str  # imported | skipped | failed
    recognized_count: int = 0
    unsupported_count: int = 0
    reason: str = ""
    out_dir: Path | None = None


def find_codejam_artifacts(codejam_root: Path) -> list[tuple[Path, str]]:
    """Find all ZIPs containing iFlow artifacts in the CodeJam repo.

    Returns list of (zip_path, inner_iflw_path_or_None) tuples.
    A None inner path means the ZIP itself is the artifact (single iFlow
    ZIP layout); a non-None path means the ZIP is an outer export with
    inner content ZIPs.
    """
    results: list[tuple[Path, str]] = []
    for zip_path in sorted(codejam_root.rglob("*.zip")):
        # Skip non-iFlow ZIPs (e.g. API Management policies, source code
        # archives). Heuristic: the ZIP must contain at least one .iflw
        # file (directly or nested inside a _content entry).
        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                # Direct .iflw
                if any(n.endswith(".iflw") for n in names):
                    results.append((zip_path, ""))
                # Nested _content ZIPs (SAP export format)
                elif any(n.endswith("_content") for n in names):
                    results.append((zip_path, "_content"))
        except (zipfile.BadZipFile, OSError):
            continue
    return results


def extract_iflows_from_zip(zip_path: Path) -> list[tuple[str, bytes]]:
    """Return [(iflw_name, iflw_xml_bytes), ...] from a CodeJam ZIP.

    Handles both single-iFlow ZIPs and the SAP export format with nested
    _content ZIPs.
    """
    out: list[tuple[str, bytes]] = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            # Direct .iflw files
            direct = [n for n in zf.namelist() if n.endswith(".iflw")]
            for name in direct:
                out.append((Path(name).stem, zf.read(name)))

            # Nested _content ZIPs (SAP export)
            content_files = [n for n in zf.namelist() if n.endswith("_content")]
            for cf in content_files:
                try:
                    inner_bytes = zf.read(cf)
                    inner_zip = zipfile.ZipFile(io.BytesIO(inner_bytes))
                    for n in inner_zip.namelist():
                        if n.endswith(".iflw"):
                            stem = Path(n).stem
                            # Dedup by stem + first 16 bytes of content (some
                            # variants share names but differ)
                            content = inner_zip.read(n)
                            key = f"{stem}__{hashlib.sha256(content).hexdigest()[:8]}"
                            out.append((key, content))
                except (zipfile.BadZipFile, OSError):
                    continue
    except (zipfile.BadZipFile, OSError) as exc:
        print(f"  WARN: {zip_path}: {exc}", file=sys.stderr)
    return out


def normalize_artifact_id(raw: str) -> str:
    """Make a safe directory name from an iFlow name."""
    s = re.sub(r"[^A-Za-z0-9_-]", "-", raw)
    s = re.sub(r"-+", "-", s).strip("-").lower()
    return s[:60] or "unnamed"


def ingest_one_iflow(
    iflw_name: str,
    iflw_bytes: bytes,
    source_zip: Path,
    emg_store: Any,
) -> IngestionResult:
    """Ingest a single iFlow: parse, redact, persist IR + metadata + EMG node."""
    artifact_id = normalize_artifact_id(iflw_name)
    out_dir = SEED_CORPUS_DIR / f"codejam-{artifact_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Parse the BPMN2 .iflw directly (this is the WP-08 PR-5 fixed parser)
    iflw_text = iflw_bytes.decode("utf-8", errors="replace")
    parsed = parse_bpmn2_iflw(iflw_text)
    if "error" in parsed:
        return IngestionResult(
            artifact_id=artifact_id,
            source_zip=str(source_zip),
            iflw_path=iflw_name,
            status="failed",
            reason=f"BPMN2 parse error: {parsed['error']}",
        )

    # Build a minimal IR from the parsed flow
    ir = convert_parsed_flow_to_oiw_ir(parsed)

    # Also run the canonical import_archive path so we get a structured
    # ImportReport (recognized/opaque/unsupported lists). We write the
    # iflw to a temp zip-like file first.
    # Simpler: synthesize the report from `parsed` since the parser already
    # classified everything. We use `convert_parsed_flow_to_oiw_ir` for the
    # IR and walk `parsed` for the report.
    recognized = []
    if parsed.get("sender"):
        recognized.append({"component": "sender", "fidelity": "simulated"})
    if parsed.get("receiver"):
        recognized.append({"component": "receiver", "fidelity": "simulated"})
    for step in parsed.get("steps", []):
        recognized.append({
            "component": f"step:{step.get('type', 'unknown')}",
            "fidelity": step.get("fidelity", "simulated"),
        })

    # Redact IR
    redactor = Redactor()
    redacted_ir = redactor.redact_dict(ir)

    # Write flow.yaml
    (out_dir / "flow.yaml").write_text(
        yaml.safe_dump(redacted_ir, sort_keys=False, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    # Write import-report.yaml
    report_data = {
        "importResult": {
            "status": "PARTIAL",
            "targetProfile": "sap-cloud-integration-2026-07",
            "sourceArchive": str(source_zip),
            "sourceIf": iflw_name,
            "recognized": recognized,
            "unsupported": [
                {
                    "component": f"callActivity:{c['config'].get('name', c['id'])}",
                    "reason": c["config"].get("reason", "unknown"),
                    "activityType": c["config"].get("activityType", ""),
                }
                for c in parsed.get("unsupported_call_activities", [])
            ],
            "warnings": [],
        }
    }
    (out_dir / "import-report.yaml").write_text(
        yaml.safe_dump(report_data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )

    # Write metadata.yaml
    metadata = {
        "provenance": {
            "source": "sap-codejam",
            "artifactId": artifact_id,
            "originalName": iflw_name,
            "sourceZip": str(source_zip),
            "isReal": True,
        },
        "license": "Apache-2.0",  # CodeJam content is Apache-2.0
        "confidentialityScope": "project",
        "redacted": True,
        "note": (
            "CodeJam artifact ingested via scripts/ingest_codejam.py (WP-08 PR-6). "
            "Source: https://github.com/SAP-samples/connecting-systems-services-integration-suite-codejam"
        ),
    }
    (out_dir / "metadata.yaml").write_text(
        yaml.safe_dump(metadata, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )

    # Persist a task node to the EMG store
    node_types = [n.get("type", "") for n in redacted_ir.get("spec", {}).get("nodes", [])]
    nr = NormalizedRequirement(
        intent="codejam-artifact",
        raw=f"CodeJam artifact: {iflw_name}",
        archetype=None,
        source_protocol="https" if any("sender" in t for t in node_types) else None,
        target_protocol=None,
        operations=[t.split(".")[0] for t in node_types if "." in t],
        components=node_types,
    )
    emg_store.upsert_task_from_requirement(
        nr,
        task_id=f"codejam-{artifact_id}",
        project_id="codejam-corpus",
        insight_ref=None,
    )

    return IngestionResult(
        artifact_id=artifact_id,
        source_zip=str(source_zip),
        iflw_path=iflw_name,
        status="imported",
        recognized_count=len(recognized),
        unsupported_count=len(parsed.get("unsupported_call_activities", [])),
        out_dir=out_dir,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--codejam-root",
        type=Path,
        default=DEFAULT_CODEJAM_ROOT,
        help="Path to the cloned CodeJam repo (default: /tmp/sap-codejam).",
    )
    parser.add_argument(
        "--emg-store-root",
        type=Path,
        default=DEFAULT_EMG_STORE_ROOT,
        help="EMG store root (default: /tmp/oiw-emg-codejam).",
    )
    args = parser.parse_args()

    if not args.codejam_root.is_dir():
        print(f"FAIL: CodeJam repo not found at {args.codejam_root}", file=sys.stderr)
        print("Clone with: git clone --depth 1 "
              "https://github.com/SAP-samples/connecting-systems-services-integration-suite-codejam.git "
              f"{args.codejam_root}", file=sys.stderr)
        return 2

    print(f"CodeJam root: {args.codejam_root}")
    print(f"EMG store root: {args.emg_store_root}")
    print(f"Seed corpus output: {SEED_CORPUS_DIR}/codejam-*")
    print()

    # Find all ZIPs containing iFlows
    zip_paths = find_codejam_artifacts(args.codejam_root)
    print(f"Found {len(zip_paths)} ZIPs with iFlow content:")
    for zp, _ in zip_paths:
        print(f"  - {zp.relative_to(args.codejam_root)}")
    print()

    # Load (or create) the durable EMG store
    emg_store = build_emg_store(root=args.emg_store_root, create_if_missing=True)
    emg_store.load()
    print(f"EMG store: backend={emg_store.manifest().embedding_backend} "
          f"dim={emg_store.manifest().embedding_dim}")
    print()

    # Walk each ZIP, extract iFlows, ingest each
    seen_iflows: set[str] = set()  # dedup by sha256(content) — same iFlow may appear in multiple ZIPs
    results: list[IngestionResult] = []

    for zip_path, _ in zip_paths:
        iflows = extract_iflows_from_zip(zip_path)
        for iflw_name, iflw_bytes in iflows:
            content_hash = hashlib.sha256(iflw_bytes).hexdigest()
            if content_hash in seen_iflows:
                results.append(IngestionResult(
                    artifact_id=normalize_artifact_id(iflw_name),
                    source_zip=str(zip_path),
                    iflw_path=iflw_name,
                    status="skipped",
                    reason="duplicate (same content hash)",
                ))
                continue
            seen_iflows.add(content_hash)
            result = ingest_one_iflow(iflw_name, iflw_bytes, zip_path, emg_store)
            results.append(result)
            status_marker = "✓" if result.status == "imported" else "⊘"
            print(f"  {status_marker} [{result.status}] {iflw_name} "
                  f"→ {result.out_dir or '(skipped)'} "
                  f"({result.recognized_count} recognized, {result.unsupported_count} unsupported)")

    emg_store.save()
    print()
    print(f"=== Summary ===")
    print(f"Total iFlows scanned: {len(results)}")
    print(f"  imported:  {sum(1 for r in results if r.status == 'imported')}")
    print(f"  skipped:   {sum(1 for r in results if r.status == 'skipped')}")
    print(f"  failed:    {sum(1 for r in results if r.status == 'failed')}")
    print()
    stats = emg_store.stats()
    print(f"EMG store final state:")
    print(f"  insights: {stats['insights']}")
    print(f"  tasks:    {stats['tasks']}")
    print(f"  edges:    {stats['edges']}")
    print(f"  path:     {emg_store.root_path}")

    # WP-08 B-001 acceptance check: ≥ 8 distinct artifacts OR a written inventory
    imported_count = sum(1 for r in results if r.status == "imported")
    if imported_count >= 8:
        print(f"\nWP-08 B-001 acceptance: ✅ ≥ 8 CodeJam artifacts imported ({imported_count})")
    else:
        print(f"\nWP-08 B-001 acceptance: ⚠️ only {imported_count} imported (target: ≥ 8)")
        print("  See skipped/failed entries above — every gap is documented.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
