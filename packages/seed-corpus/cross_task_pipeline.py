"""Cross-task pattern discovery (WP-07 Track C).

Spec ref: §15.13 (Cross-Task Transfer).

C-001 Archetype Clustering:
  Group all ingested artifacts (CodeJam + blog patterns + synthetic
  variations + learning sessions) by integration archetype.

C-002 Expert-to-Expert Matching Within Archetypes:
  For each archetype with ≥ 2 artifacts, run ExpertToExpertMatcher
  between every pair of expert trajectories.

C-003 Cross-Task Edge Population:
  For matches with confidence > 0.5, generate a CrossTaskInsight and
  store it as a CrossTaskEdge. Target: ≥ 15 cross-task edges spanning
  ≥ 4 archetypes.

C-004 Retrieval Verification:
  Smoke-test that the edge store returns relevant edges for matching
  requirements.
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "seed-corpus"))

from oiw.agent.trajectory import (
    EngineeringTrajectory,
)
from oiw.emg.edge_store import CrossTaskEdgeStore
from oiw.emg.graph_builder import ActionDecisionGraphBuilder
from oiw.emg.insight.cross_task import (
    CrossTaskInsightGenerator,
)
from oiw.emg.matching.expert_to_expert import ExpertToExpertMatcher
from oiw.emg.task_store import TaskMemoryNode
from synthesize_trajectory import synthesize_expert_trajectory

# --------------------------------------------------------------------------- #
# C-001: Archetype classification
# --------------------------------------------------------------------------- #

# Archetype detection rules — based on adapter types and operations
_ARCHETYPE_RULES = [
    # (archetype_name, matcher_fn) — order matters: more specific first
    (
        "paginated-api-ingestion",
        lambda ir: _has_receiver(ir, "odata") and _has_sender(ir, "http"),
    ),
    ("api-validation", lambda ir: _has_operation(ir, "validate")),
    ("file-to-api", lambda ir: _has_sender(ir, "sftp") and _has_receiver(ir, "http")),
    ("api-to-file", lambda ir: _has_sender(ir, "http") and _has_receiver(ir, "sftp")),
    (
        "soap-integration",
        lambda ir: _has_sender(ir, "soap") or _has_receiver(ir, "soap"),
    ),
    ("idoc-integration", lambda ir: _has_receiver(ir, "idoc")),
    ("mail-integration", lambda ir: _has_receiver(ir, "mail")),
    (
        "api-to-erp",
        lambda ir: _has_sender(ir, "http")
        and _has_receiver(ir, "http")
        and _has_operation(ir, "transform"),
    ),
    ("api-to-api", lambda ir: _has_sender(ir, "http") and _has_receiver(ir, "http")),
    ("transform-pipeline", lambda ir: _has_operation(ir, "transform")),
    (
        "event-driven-webhook",
        lambda ir: _has_sender(ir, "http") and _has_operation(ir, "route"),
    ),
    (
        "batch-etl",
        lambda ir: _has_operation(ir, "split") or _has_operation(ir, "gather"),
    ),
    (
        "error-handling-pattern",
        lambda ir: bool(ir.get("spec", {}).get("errorHandling")),
    ),
]


def _has_sender(ir: dict, protocol: str) -> bool:
    for ep in ir.get("spec", {}).get("entrypoints", []):
        if protocol in ep.get("type", ""):
            return True
    for n in ir.get("spec", {}).get("nodes", []):
        if n.get("type", "").startswith("sender") and protocol in n.get("type", ""):
            return True
    return False


def _has_receiver(ir: dict, protocol: str) -> bool:
    for n in ir.get("spec", {}).get("nodes", []):
        if n.get("type", "").startswith("receiver") and protocol in n.get("type", ""):
            return True
    return False


def _has_operation(ir: dict, op: str) -> bool:
    op_map = {
        "transform": ("transform", "xslt", "script", "groovy", "converter"),
        "validate": ("validator",),
        "route": ("router",),
        "filter": ("filter",),
        "split": ("splitter",),
        "gather": ("gather",),
    }
    keywords = op_map.get(op, ())
    for n in ir.get("spec", {}).get("nodes", []):
        ntype = n.get("type", "")
        if any(k in ntype for k in keywords):
            return True
    return False


def classify_archetype(ir: dict[str, Any]) -> str:
    """Classify an IR into an integration archetype.

    Returns the first matching archetype from _ARCHETYPE_RULES, or
    "unknown" if no rule matches.
    """
    for name, matcher in _ARCHETYPE_RULES:
        try:
            if matcher(ir):
                return name
        except Exception:  # noqa: BLE001
            continue
    return "unknown"


@dataclass
class Artifact:
    """A loaded artifact with its IR and metadata."""

    artifact_id: str
    source: str  # "oiw-example" | "synthetic-original" | "synthetic-variation" | "blog-pattern" | "learning-session"
    flow_id: str
    ir: dict[str, Any]
    archetype: str
    trajectory: EngineeringTrajectory | None = None
    license_spdx: str = "Apache-2.0"
    is_real: bool = False
    artifact_dir: Path | None = None  # resolved source directory


def cluster_by_archetype(artifacts: list[Artifact]) -> dict[str, list[Artifact]]:
    """Group artifacts by integration archetype.

    Returns a dict: {archetype: [Artifact, ...]}.
    """
    clusters: dict[str, list[Artifact]] = {}
    for a in artifacts:
        clusters.setdefault(a.archetype, []).append(a)
    return clusters


# --------------------------------------------------------------------------- #
# Artifact loading
# --------------------------------------------------------------------------- #


def _load_ir_from_dir(artifact_dir: Path) -> dict[str, Any] | None:
    """Load flow.yaml from an artifact directory."""
    flow_path = artifact_dir / "flow.yaml"
    if not flow_path.is_file():
        return None
    try:
        return yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def load_all_artifacts(
    seed_corpus_dir: Path | str | None = None,
    artifacts_dir: Path | str | None = None,
) -> list[Artifact]:
    """Load all ingested artifacts (OIW examples + synthetic + blog patterns).

    Loads from:
      - examples/order-to-s4/flows/
      - examples/sftp-order-drop/flows/
      - artifacts_dir (or seed_corpus_dir/artifacts/) — synthetic + blog patterns + CodeJam

    If the artifacts_dir is empty, populates it on the fly via
    populate_corpus (so cross-task discovery always has data to work with).

    Returns a flat list of Artifact objects.
    """
    if seed_corpus_dir is None:
        seed_corpus_dir = REPO_ROOT / "packages" / "seed-corpus"
    seed_corpus_dir = Path(seed_corpus_dir)
    if artifacts_dir is None:
        artifacts_dir = seed_corpus_dir / "artifacts"
    artifacts_dir = Path(artifacts_dir)

    artifacts: list[Artifact] = []

    # 1. OIW example flows
    for example in ["order-to-s4", "sftp-order-drop"]:
        flows_dir = REPO_ROOT / "examples" / example / "flows"
        if not flows_dir.is_dir():
            continue
        for flow_dir in sorted(flows_dir.iterdir()):
            if not flow_dir.is_dir():
                continue
            ir = _load_ir_from_dir(flow_dir)
            if ir is None:
                continue
            flow_id = ir.get("metadata", {}).get("id", flow_dir.name)
            artifacts.append(
                Artifact(
                    artifact_id=f"oiw-{flow_id}",
                    source="oiw-example",
                    flow_id=flow_id,
                    ir=ir,
                    archetype=classify_archetype(ir),
                    license_spdx="Apache-2.0",
                    is_real=True,
                    artifact_dir=flow_dir,
                )
            )

    # 2. Seed corpus artifacts — populate if empty
    if not artifacts_dir.is_dir() or not any(artifacts_dir.iterdir()):
        from populate_corpus import populate_corpus

        populate_corpus(output_dir=artifacts_dir)

    if artifacts_dir.is_dir():
        for art_dir in sorted(artifacts_dir.iterdir()):
            if not art_dir.is_dir():
                continue
            ir = _load_ir_from_dir(art_dir)
            if ir is None:
                continue
            flow_id = ir.get("metadata", {}).get("id", art_dir.name)
            # Determine source from artifact_id prefix
            art_name = art_dir.name.lower()
            if "blog" in art_name or "bp-" in art_name:
                source = "blog-pattern"
                is_real = True
            elif "codejam" in art_name or "cj-" in art_name:
                source = "sap-codejam"
                is_real = True
            else:
                source = "synthetic-variation"
                is_real = False
            artifacts.append(
                Artifact(
                    artifact_id=art_dir.name,
                    source=source,
                    flow_id=flow_id,
                    ir=ir,
                    archetype=classify_archetype(ir),
                    license_spdx="Apache-2.0",
                    is_real=is_real,
                    artifact_dir=art_dir,
                )
            )

    return artifacts


# --------------------------------------------------------------------------- #
# C-002 + C-003: Expert matching + edge population
# --------------------------------------------------------------------------- #


def _ensure_trajectory(artifact: Artifact) -> EngineeringTrajectory:
    """Synthesize a trajectory for the artifact if not already done."""
    if artifact.trajectory is not None:
        return artifact.trajectory

    # Prefer the resolved artifact_dir captured at load time
    artifact_dir = artifact.artifact_dir
    if artifact_dir is None or not artifact_dir.is_dir():
        # Fall back to repo-relative search
        if artifact.source == "oiw-example":
            for example in ["order-to-s4", "sftp-order-drop"]:
                candidate = (
                    REPO_ROOT / "examples" / example / "flows" / artifact.flow_id
                )
                if candidate.is_dir():
                    artifact_dir = candidate
                    break
        else:
            candidate = (
                REPO_ROOT
                / "packages"
                / "seed-corpus"
                / "artifacts"
                / artifact.artifact_id
            )
            if candidate.is_dir():
                artifact_dir = candidate

    if artifact_dir is None:
        raise FileNotFoundError(f"artifact dir not found for {artifact.artifact_id}")

    artifact.trajectory = synthesize_expert_trajectory(artifact_dir)
    return artifact.trajectory


def _build_task_memory_node(artifact: Artifact) -> TaskMemoryNode:
    """Build a TaskMemoryNode from an artifact for the edge store."""
    traj = _ensure_trajectory(artifact)
    spec = artifact.ir.get("spec", {})

    # Determine protocols
    source_protocol = None
    for ep in spec.get("entrypoints", []):
        ep_type = ep.get("type", "")
        if "http" in ep_type:
            source_protocol = "https"
        elif "sftp" in ep_type:
            source_protocol = "sftp"
        elif "soap" in ep_type:
            source_protocol = "soap"

    target_protocol = None
    for n in reversed(spec.get("nodes", [])):
        ntype = n.get("type", "")
        if ntype.startswith("receiver"):
            if "http" in ntype:
                target_protocol = "https"
            elif "sftp" in ntype:
                target_protocol = "sftp"
            elif "soap" in ntype:
                target_protocol = "soap"
            elif "odata" in ntype:
                target_protocol = "odata"
            elif "idoc" in ntype:
                target_protocol = "idoc"
            elif "mail" in ntype:
                target_protocol = "smtp"
            break

    return TaskMemoryNode(
        id=f"task-mem-{uuid.uuid4().hex[:12]}",
        task_id=traj.metadata.taskId or traj.metadata.id,
        requirement_embedding=[],  # not needed for cross-task matching
        normalized_requirement={
            "intent": "create-flow",
            "archetype": artifact.archetype,
            "source_protocol": source_protocol,
            "target_protocol": target_protocol,
            "operations": [],
        },
        insight_ref=None,
        reward=traj.spec.outcome.reward or {},
        approval="PROJECT_APPROVED",
        target_profiles=["sap-cloud-integration-2026-07"],
        confidentiality_scope="project",
        project_id="seed-corpus",
    )


def populate_cross_task_edges(
    artifacts: list[Artifact],
    edge_store: CrossTaskEdgeStore | None = None,
    min_confidence: float = 0.5,
) -> dict[str, Any]:
    """C-002 + C-003: Match expert pairs within archetypes and store edges.

    Returns a summary dict with edge count + per-archetype breakdown.
    """
    if edge_store is None:
        edge_store = CrossTaskEdgeStore()

    clusters = cluster_by_archetype(artifacts)
    matcher = ExpertToExpertMatcher()
    insight_gen = CrossTaskInsightGenerator()
    builder = ActionDecisionGraphBuilder()

    edges_per_archetype: dict[str, int] = {}
    matches_run = 0
    matches_kept = 0
    matches_rejected = 0

    for archetype, arts in clusters.items():
        if len(arts) < 2:
            continue

        # Build task memory nodes + ADGs once per artifact
        task_nodes: list[tuple[Artifact, TaskMemoryNode, Any]] = []
        for a in arts:
            try:
                traj = _ensure_trajectory(a)
                adg = builder.build(traj)
                tn = _build_task_memory_node(a)
                task_nodes.append((a, tn, adg))
            except Exception:  # noqa: BLE001
                continue

        # Match every pair within the archetype
        for i in range(len(task_nodes)):
            for j in range(i + 1, len(task_nodes)):
                _a_art, a_tn, a_adg = task_nodes[i]
                _b_art, b_tn, b_adg = task_nodes[j]
                matches_run += 1
                try:
                    match = matcher.match(a_adg, b_adg)
                except Exception:  # noqa: BLE001
                    continue

                if match.stage == "rejected":
                    matches_rejected += 1
                    continue

                if match.confidence < min_confidence:
                    matches_rejected += 1
                    continue

                # Generate cross-task insight
                insight = insight_gen.generate(a_tn, b_tn, match)
                if insight is None:
                    matches_rejected += 1
                    continue

                # Add edge in both directions (cross-task is symmetric in retrieval)
                edge_store.add_edge(
                    source_task_id=a_tn.task_id,
                    target_task_id=b_tn.task_id,
                    insight=insight,
                    similarity_score=match.confidence,
                )
                edge_store.add_edge(
                    source_task_id=b_tn.task_id,
                    target_task_id=a_tn.task_id,
                    insight=insight,
                    similarity_score=match.confidence,
                )
                matches_kept += 1
                edges_per_archetype[archetype] = (
                    edges_per_archetype.get(archetype, 0) + 2
                )

    return {
        "totalArtifacts": len(artifacts),
        "archetypesWithEdges": len(edges_per_archetype),
        "edgesPerArchetype": edges_per_archetype,
        "totalEdges": edge_store.count(),
        "matchesRun": matches_run,
        "matchesKept": matches_kept,
        "matchesRejected": matches_rejected,
        "edgeStore": edge_store,
    }


# --------------------------------------------------------------------------- #
# C-004: Retrieval verification
# --------------------------------------------------------------------------- #


def verify_cross_task_retrieval(
    edge_store: CrossTaskEdgeStore,
    artifacts: list[Artifact],
    sample_size: int = 5,
) -> dict[str, Any]:
    """Verify that cross-task edges are retrievable for matching tasks.

    Picks a sample of artifacts and checks that get_edges_for_task returns
    at least one edge for each.
    """
    results = []
    sample = artifacts[:sample_size] if len(artifacts) >= sample_size else artifacts

    for art in sample:
        try:
            traj = _ensure_trajectory(art)
            task_id = traj.metadata.taskId or traj.metadata.id
            edges = edge_store.get_edges_for_task(
                task_id, min_confidence=0.0, max_edges=5
            )
            results.append(
                {
                    "artifact_id": art.artifact_id,
                    "archetype": art.archetype,
                    "edgesFound": len(edges),
                    "topConfidence": edges[0].insight.confidence if edges else None,
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "artifact_id": art.artifact_id,
                    "archetype": art.archetype,
                    "edgesFound": 0,
                    "error": str(exc),
                }
            )

    return {
        "sampleSize": len(sample),
        "withEdges": sum(1 for r in results if r["edgesFound"] > 0),
        "results": results,
    }


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #


def run_cross_task_pipeline() -> dict[str, Any]:
    """Run the full Track C pipeline: cluster → match → populate → verify."""
    artifacts = load_all_artifacts()
    clusters = cluster_by_archetype(artifacts)
    pop_result = populate_cross_task_edges(artifacts)
    verify_result = verify_cross_task_retrieval(
        pop_result["edgeStore"], artifacts, sample_size=5
    )

    return {
        "totalArtifacts": len(artifacts),
        "archetypeClusters": {k: len(v) for k, v in sorted(clusters.items())},
        "archetypesWithThreePlus": sum(1 for v in clusters.values() if len(v) >= 3),
        "edges": {
            "total": pop_result["totalEdges"],
            "perArchetype": pop_result["edgesPerArchetype"],
            "matchesRun": pop_result["matchesRun"],
            "matchesKept": pop_result["matchesKept"],
            "matchesRejected": pop_result["matchesRejected"],
        },
        "retrieval": verify_result,
    }


if __name__ == "__main__":
    summary = run_cross_task_pipeline()
    # Don't dump the edge store
    summary.pop("edgeStore", None)
    print(yaml.safe_dump(summary, sort_keys=False, default_flow_style=False))
