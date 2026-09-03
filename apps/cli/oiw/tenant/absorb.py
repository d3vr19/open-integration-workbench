"""Phase 2 — tenant absorption: the ~600 flows become EMG experience.

`oiw tenant absorb` crawls every visible package (read-only GETs),
pulls each artifact through the proven pipeline —
download → import → redact → persist (gitignored, customer-content) —
and promotes a PROJECT_APPROVED insight per flow into the durable EMG
store with `provenance.source=tenant-catalog`.

Laws honored:
  - Read-only: no writes, no scratch packages, safe against prod tenants.
  - Customer content: artifacts land under .oiw/tenant-corpus/
    (gitignored). license=customer-content, learning-only, never
    redistributed. Only the redacted IR shape + node-type chain feed the
    EMG — no hostnames, no secrets (Redactor runs on everything).
  - Honest provenance: match_stage='tenant-catalog', seed-discount
    confidence (these flows RUN, but we have not exercised them via the
    oracle — calibrate-grade knowledge is worth more).
  - Budgets: max_artifacts + per-package caps + polite delay between
    downloads; resumable (content-hash dedup skips re-pulls).
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..agent.interpreter import NormalizedRequirement
from ..agent.redaction import Redactor
from ..compiler.sap_flow_parser import parse_bpmn2_iflw
from ..emg.insight.compiler import InsightProvenance, IntraTaskInsight
from ..emg.promotion import InsightRecord, MemoryPromotionState
from .sap_ci_adapter import SapCiTenantAdapter, SapCiTenantError

ABSORB_CORPUS_DIR = Path(".oiw") / "tenant-corpus"
ABSORB_PROVENANCE_SOURCE = "tenant-catalog"
# Seed-style confidence discount: catalog knowledge ran on the tenant but
# was not exercised through OUR oracle loop.
CATALOG_DISCOUNT = 0.8


@dataclass
class AbsorbStats:
    """One crawl's summary."""

    packages_scanned: int = 0
    artifacts_seen: int = 0
    artifacts_pulled: int = 0
    artifacts_deduped: int = 0
    insights_promoted: int = 0
    tasks_upserted: int = 0
    failures: list[str] = field(default_factory=list)

    def summary_line(self) -> str:
        return (
            f"packages={self.packages_scanned} seen={self.artifacts_seen} "
            f"pulled={self.artifacts_pulled} deduped={self.artifacts_deduped} "
            f"insights={self.insights_promoted} tasks={self.tasks_upserted} "
            f"failures={len(self.failures)}"
        )


def _content_hash(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()[:16]


def _safe_id(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)


def flow_shape_from_ir(ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Serialize an imported IR's node chain into insight workflow form
    (same shape as learn.loop._flow_success_shape — action tuples).
    Entrypoints are part of the chain (senders are real pieces)."""
    spec = ir.get("spec", {}) or {}
    entry_ids = [e.get("id") for e in spec.get("entrypoints", []) or []]
    nodes = {n.get("id"): n for n in spec.get("nodes", []) or []}
    # Entrypoints participate in the BFS even though they live outside spec.nodes.
    order: list[str] = []
    seen: set[str] = set()
    queue: list[str] = [e for e in entry_ids if e]
    edges = spec.get("edges", []) or []
    while queue:
        nid = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        order.append(nid)
        for e in edges:
            if e.get("from") == nid and e.get("to") not in seen:
                queue.append(e.get("to"))
    for nid in nodes:
        if nid not in seen:
            order.append(nid)

    def _type_of(nid: str) -> str:
        if nid in nodes:
            return str(nodes[nid].get("type", "unknown"))
        for e in spec.get("entrypoints", []) or []:
            if e.get("id") == nid:
                return str(e.get("type", "unknown"))
        return "unknown"

    return [
        {
            "action": ("flow.patch", "addNode", _type_of(nid), nid),
            "result": "applied",
        }
        for nid in order
    ]


def requirement_for_artifact(package_id: str, artifact_id: str, ir: dict[str, Any]) -> NormalizedRequirement:
    """Synthesize the searchable requirement for one absorbed flow."""
    spec = ir.get("spec", {}) or {}
    node_types = [str(n.get("type", "")) for n in spec.get("nodes", []) or []]
    entry_types = [str(e.get("type", "")) for e in spec.get("entrypoints", []) or []]
    senders = [t for t in entry_types if t.startswith("sender.")]
    receivers = [t for t in node_types if t.startswith("receiver.")]
    arch = None
    if senders and receivers:
        arch = f"{senders[0].split('.', 1)[1]}-to-{receivers[0].split('.', 1)[1]}"
    return NormalizedRequirement(
        intent="tenant-artifact",
        raw=(
            f"Tenant flow {artifact_id} in package {package_id}: "
            f"entrypoints {sorted(set(entry_types))}, steps {sorted(set(node_types))}"
        ),
        archetype=arch,
        source_protocol=senders[0].split(".", 1)[1] if senders else None,
        target_protocol=receivers[0].split(".", 1)[1] if receivers else None,
        operations=sorted({t.split(".")[0] for t in node_types if "." in t}),
        components=sorted(set(node_types + entry_types)),
        constraints=[],
        confidence=CATALOG_DISCOUNT,
    )


async def absorb_tenant(
    adapter: SapCiTenantAdapter,
    durable_store: Any,
    *,
    max_artifacts: int = 600,
    per_package_cap: int = 30,
    package_ids: list[str] | None = None,
    corpus_dir: Path | None = None,
    delay_s: float = 0.1,
    progress=None,
) -> AbsorbStats:
    """Crawl the tenant catalog and promote every flow into the EMG store.

    Read-only against the tenant. `durable_store` is a JsonlEmgStore.
    """
    stats = AbsorbStats()
    redactor = Redactor()
    corpus = corpus_dir or ABSORB_CORPUS_DIR
    corpus.mkdir(parents=True, exist_ok=True)

    # The adapter may arrive unconnected (CLI builds it from env) — then
    # the crawl owns the full lifecycle. Tests inject a transport-backed
    # adapter and keep the connection across crawls.
    owns_connection = not adapter.is_connected
    if owns_connection:
        await adapter.connect(_absorb_profile())
    try:
        return await _absorb_connected(
            adapter,
            durable_store,
            stats,
            redactor,
            corpus,
            max_artifacts=max_artifacts,
            per_package_cap=per_package_cap,
            package_ids=package_ids,
            delay_s=delay_s,
            progress=progress,
        )
    finally:
        if owns_connection:
            await adapter.disconnect()


def _absorb_profile() -> Any:
    """Minimal profile for connect(): credentials come from env vars."""
    from ..environments import AuthConfig, DeploymentPolicy, EnvironmentProfile

    return EnvironmentProfile(
        name="absorb",
        target="sap-cloud-integration-2026-07",
        auth=AuthConfig(method="basic", credential_ref="absorb"),
        deployment_policy=DeploymentPolicy(requires_approval=False),
    )


async def _absorb_connected(
    adapter: SapCiTenantAdapter,
    durable_store: Any,
    stats: AbsorbStats,
    redactor: Redactor,
    corpus: Path,
    *,
    max_artifacts: int,
    per_package_cap: int,
    package_ids: list[str] | None,
    delay_s: float,
    progress=None,
) -> AbsorbStats:
    # Content-hash ledger for dedup/resume.
    ledger_path = corpus / "ledger.yaml"
    ledger: dict[str, str] = {}
    if ledger_path.is_file():
        try:
            ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            ledger = {}

    packages = await adapter.list_packages(top=200)
    if package_ids:
        wanted = set(package_ids)
        packages = [p for p in packages if p.id in wanted]
    stats.packages_scanned = len(packages)

    budget = max_artifacts
    for pkg in packages:
        if budget <= 0:
            break
        try:
            artifacts = await adapter.list_artifacts(pkg.id, top=per_package_cap)
        except SapCiTenantError as exc:
            stats.failures.append(f"{pkg.id}: list failed: {exc}")
            continue
        for art in artifacts:
            if budget <= 0:
                break
            stats.artifacts_seen += 1
            key = f"{pkg.id}/{art.id}"
            try:
                blob = await adapter.download_artifact(art.id, art.version)
            except SapCiTenantError as exc:
                stats.failures.append(f"{key}: download failed: {exc}")
                continue
            budget -= 1
            stats.artifacts_pulled += 1
            digest = _content_hash(blob)
            if ledger.get(key) == digest:
                stats.artifacts_deduped += 1
                continue  # unchanged since last absorb — EMG already has it
            ledger[key] = digest

            if progress:
                progress(key, digest)

            # Persist the redacted artifact (customer-content, gitignored).
            art_dir = corpus / f"{_safe_id(pkg.id)}-{_safe_id(art.id)}"
            art_dir.mkdir(parents=True, exist_ok=True)
            zip_path = art_dir / "source.zip"
            zip_path.write_bytes(blob)

            ir: dict[str, Any] | None = None
            try:
                ir = _ir_from_zip(zip_path, art.id)
            except Exception as exc:
                stats.failures.append(f"{key}: parse failed: {exc}")
            if ir is None:
                # Non-iFlow artifact (value mapping, script collection) —
                # nothing to learn from for flow assembly; move on.
                continue

            redacted_ir = redactor.redact_dict(ir)
            (art_dir / "flow.yaml").write_text(
                yaml.safe_dump(redacted_ir, sort_keys=True, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
            (art_dir / "metadata.yaml").write_text(
                yaml.safe_dump(
                    {
                        "provenance": {
                            "source": ABSORB_PROVENANCE_SOURCE,
                            "packageId": pkg.id,
                            "artifactId": art.id,
                            "artifactVersion": art.version,
                            "isReal": True,
                            "contentHash": digest,
                            "absorbedAt": datetime.now(tz=UTC).isoformat(),
                        },
                        "license": "customer-content",
                        "confidentialityScope": "organization",
                        "redacted": True,
                        "note": "Tenant-catalog absorption. Original ZIP stays gitignored; only the redacted IR shape feeds the EMG.",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            # Promote insight + task node into the durable store.
            insight = IntraTaskInsight(
                task_id=f"catalog-{_safe_id(pkg.id)}-{_safe_id(art.id)}",
                successful_workflow=flow_shape_from_ir(redacted_ir),
                corrections=[],
                provenance=InsightProvenance(
                    exploration_trajectory_id=f"catalog:{art.id}",
                    expert_trajectory_id=f"catalog:{art.id}",
                    match_stage=ABSORB_PROVENANCE_SOURCE,
                ),
            )
            record = InsightRecord(
                id=f"insight-{hashlib.sha256(key.encode()).hexdigest()[:12]}",
                state=MemoryPromotionState.PROJECT_APPROVED,
                trajectory_id=f"catalog:{art.id}",
                project_id="tenant-corpus",
                insight=insight,
                reviewed_by="tenant-catalog-bot",
                approved_by="tenant-catalog-bot",
            )
            durable_store.upsert_insight(record)
            stats.insights_promoted += 1
            durable_store.upsert_task_from_requirement(
                requirement_for_artifact(pkg.id, art.id, redacted_ir),
                task_id=insight.task_id,
                project_id="tenant-corpus",
                insight_ref=record.id,
                reward={"overall": CATALOG_DISCOUNT, "source": ABSORB_PROVENANCE_SOURCE},
                approval="PROJECT_APPROVED",
                confidentiality_scope="organization",
            )
            stats.tasks_upserted += 1
            if delay_s > 0:
                await asyncio.sleep(delay_s)

    ledger_path.write_text(yaml.safe_dump(ledger, sort_keys=True), encoding="utf-8")
    durable_store.save()
    return stats


def _ir_from_zip(zip_path: Path, artifact_id: str) -> dict[str, Any] | None:
    """Parse the .iflw inside a pulled artifact via the FULL BPMN2 parser
    (sap_flow_parser.parse_bpmn2_iflw — the WP-08 PR-5 classifier that maps
    callActivity activityTypes to real OIW types WITH configs). Falls back
    to None when the artifact carries no parseable iFlow (value mappings,
    script collections, etc.)."""
    import zipfile as _zf

    try:
        zf = _zf.ZipFile(zip_path)
    except Exception:
        return None
    for name in zf.namelist():
        if not name.endswith(".iflw"):
            continue
        xml = zf.read(name).decode("utf-8", errors="replace")
        try:
            parsed = parse_bpmn2_iflw(xml)
        except Exception:
            return None
        return _ir_from_parsed(parsed, artifact_id)
    return None


def _ir_from_parsed(parsed: dict[str, Any], artifact_id: str) -> dict[str, Any] | None:
    """Convert a full parse result into a minimal-but-typed IR."""
    sender = parsed.get("sender") or {}
    entry_type = {
        "HTTPS": "sender.http",
        "HTTP": "sender.http",
        "SOAP": "sender.soap",
        "ODATA_V4": "sender.odata",
        "SFTP": "sender.sftp",
        "PROCESSDIRECT": "sender.processdirect",
        "IDOC": "sender.idoc",
    }.get(str(sender.get("type", "HTTPS")).upper(), None)
    if entry_type is None and str(sender.get("type", "")).upper():
        entry_type = "sender.http"  # unknown sender dialect — closest proven shape
    entrypoints = (
        [{"id": "sender-main", "type": entry_type, "config": {}, "fidelity": "simulated"}]
        if entry_type
        else []
    )
    nodes = []
    for step in parsed.get("steps", []) or []:
        stype = str(step.get("type", ""))
        if not stype:
            continue
        cfg = dict(step.get("config") or {})
        # WP-10 H9: classify ExternalCall serviceTasks as mid-flow receiver.http in absorb's IR builder
        act_type = cfg.get("activityType") or (cfg.get("properties") or {}).get("activityType")
        if (stype == "ServiceTask" or stype == "ExternalCall") and act_type == "ExternalCall":
            stype = "receiver.http"
        cfg.pop("properties", None)  # raw tables stay in the redacted flow.yaml? no — drop bulk
        nodes.append(
            {
                "id": str(step.get("id") or f"n-{len(nodes)}"),
                "type": stype,
                "config": cfg,
                "fidelity": str(step.get("fidelity", "simulated")),
            }
        )
    receiver = parsed.get("receiver") or {}
    recv_type = str(receiver.get("type", "")).upper()
    if recv_type:
        mapped = {
            "HTTP": "receiver.http",
            "HTTPS": "receiver.http",
            "ODATA_V4": "receiver.odata-v4",
            "ODATA_V2": "receiver.odata-v4",
            "SFTP": "receiver.sftp",
            "SOAP": "receiver.soap",
            "PROCESSDIRECT": "receiver.processdirect",
            "IDOC": "receiver.idoc",
        }.get(recv_type)
        if mapped:
            nodes.append({"id": "receiver-out", "type": mapped, "config": {}, "fidelity": "simulated"})
    if not nodes and not entrypoints:
        return None
    ids = [e["id"] for e in entrypoints] + [n["id"] for n in nodes]
    return {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationFlow",
        "metadata": {"id": _safe_id(artifact_id), "name": artifact_id, "version": 1},
        "spec": {
            "entrypoints": entrypoints,
            "nodes": nodes,
            "edges": [{"from": ids[i], "to": ids[i + 1]} for i in range(len(ids) - 1)],
            "extensions": {},
        },
    }


__all__ = [
    "ABSORB_CORPUS_DIR",
    "ABSORB_PROVENANCE_SOURCE",
    "AbsorbStats",
    "absorb_tenant",
    "flow_shape_from_ir",
    "requirement_for_artifact",
]
