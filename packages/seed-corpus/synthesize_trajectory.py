"""Synthetic expert trajectory generator (WP-06 Task A-003).

Spec ref: §15.14 (Seed Corpus).

Decomposes a finished integration artifact (flow.yaml + resources + tests)
into a synthetic EngineeringTrajectory — the sequence of typed actions a
consultant would have taken to build it from scratch.

The generated trajectory is what the EMG stores and retrieves: when a
new requirement matches a seed trajectory's pattern, the expert workflow
is injected directly into the plan (mechanics-first, no LLM call).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import yaml

# Make oiw importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.agent.interpreter import NormalizedRequirement  # noqa: E402
from oiw.agent.normalization import normalize_action  # noqa: E402
from oiw.agent.trajectory import (  # noqa: E402
    ActionRecord,
    EngineeringTrajectory,
    ObservationRecord,
    ResultRecord,
    TrajectoryMetadata,
    TrajectoryOutcome,
    TrajectoryQuery,
    TrajectorySpec,
    TrajectoryStep,
)
from oiw.emg.reward import compute_reward  # noqa: E402


def synthesize_expert_trajectory(
    artifact_dir: Path | str,
    project_id: str = "seed-corpus",
) -> EngineeringTrajectory:
    """Decompose a finished artifact into a synthetic expert trajectory.

    Args:
        artifact_dir: Directory containing flow.yaml + resources/ + tests/.
        project_id: The project ID for the trajectory metadata.

    Returns:
        EngineeringTrajectory with steps for flow.create, addNode (per
        node in topological order), resource.write (per resource),
        addEdge (per edge), test.create (per test), flow.validate, build.
    """
    artifact_dir = Path(artifact_dir)

    # Load the flow IR
    flow_path = artifact_dir / "flow.yaml"
    if not flow_path.is_file():
        raise FileNotFoundError(f"flow.yaml not found in {artifact_dir}")

    ir = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    metadata = ir.get("metadata", {})
    spec = ir.get("spec", {})
    nodes = spec.get("nodes", [])
    edges = spec.get("edges", [])
    entrypoints = spec.get("entrypoints", [])

    flow_id = metadata.get("id", artifact_dir.name)
    flow_name = metadata.get("name", flow_id)

    steps: list[TrajectoryStep] = []
    step_index = 0

    # 1. Create the flow
    steps.append(
        _make_step(
            step_index,
            obs_type="project.snapshot",
            obs_summary={"flows": []},
            action_type="flow.create",
            action_normalized=("flow.create", "create-flow", flow_id, "", ""),
            action_args={"flowId": flow_id, "name": flow_name},
            result_status="applied",
            result_summary=f"Created flow '{flow_name}'",
        )
    )
    step_index += 1

    # 2. Add entrypoints (senders)
    for ep in entrypoints:
        ep_type = ep.get("type", "sender.http")
        steps.append(
            _make_step(
                step_index,
                obs_type="flow.snapshot",
                obs_summary={"nodes": [n.get("id") for n in nodes[:1]]},
                action_type="flow.patch",
                action_normalized=normalize_action(
                    "flow.patch",
                    {"operations": [{"op": "addNode", "node": {"type": ep_type}}]},
                ),
                action_args={"operations": [{"op": "addNode", "node": ep}]},
                result_status="applied",
                result_summary=f"Added entrypoint {ep.get('id', ep_type)}",
            )
        )
        step_index += 1

    # 3. Add processing nodes in topological order
    topo_nodes = _topological_sort(nodes, edges)
    for node in topo_nodes:
        node_type = node.get("type", "log.message")
        steps.append(
            _make_step(
                step_index,
                obs_type="flow.snapshot",
                obs_summary={"lastNode": steps[-1].action.type if steps else None},
                action_type="flow.patch",
                action_normalized=normalize_action(
                    "flow.patch",
                    {"operations": [{"op": "addNode", "node": {"type": node_type}}]},
                ),
                action_args={"operations": [{"op": "addNode", "node": node}]},
                result_status="applied",
                result_summary=f"Added node {node.get('id', node_type)}",
            )
        )
        step_index += 1

    # 4. Add resources (Groovy, XSLT, schemas)
    resources_dir = artifact_dir / "resources"
    if resources_dir.is_dir():
        for res_path in sorted(resources_dir.rglob("*")):
            if not res_path.is_file():
                continue
            rel_path = str(res_path.relative_to(artifact_dir))
            steps.append(
                _make_step(
                    step_index,
                    obs_type="flow.snapshot",
                    obs_summary={"resources": [rel_path]},
                    action_type="resource.write",
                    action_normalized=normalize_action(
                        "resource.write", {"path": rel_path}
                    ),
                    action_args={
                        "path": rel_path,
                        "content": res_path.read_text(
                            encoding="utf-8", errors="replace"
                        ),
                    },
                    result_status="applied",
                    result_summary=f"Added resource {rel_path}",
                )
            )
            step_index += 1

    # 5. Connect edges
    for edge in edges:
        from_id = edge.get("from", "")
        to_id = edge.get("to", "")
        steps.append(
            _make_step(
                step_index,
                obs_type="flow.snapshot",
                obs_summary={"edges": [f"{from_id}->{to_id}"]},
                action_type="flow.patch",
                action_normalized=normalize_action(
                    "flow.patch",
                    {"operations": [{"op": "addEdge", "from": from_id, "to": to_id}]},
                ),
                action_args={
                    "operations": [{"op": "addEdge", "from": from_id, "to": to_id}]
                },
                result_status="applied",
                result_summary=f"Connected {from_id} → {to_id}",
            )
        )
        step_index += 1

    # 6. Create tests
    tests_dir = artifact_dir / "tests"
    if tests_dir.is_dir():
        for test_file in sorted(tests_dir.glob("*.yaml")):
            steps.append(
                _make_step(
                    step_index,
                    obs_type="flow.snapshot",
                    obs_summary={"tests": [test_file.stem]},
                    action_type="test.create",
                    action_normalized=normalize_action(
                        "test.create", {"flowId": flow_id}
                    ),
                    action_args={"testName": test_file.stem, "flowId": flow_id},
                    result_status="applied",
                    result_summary=f"Created test '{test_file.stem}'",
                )
            )
            step_index += 1

    # 7. Validate
    steps.append(
        _make_step(
            step_index,
            obs_type="flow.snapshot",
            obs_summary={"complete": True},
            action_type="flow.validate",
            action_normalized=("flow.validate", "invoke", "project", "", ""),
            action_args={"strict": True},
            result_status="applied",
            result_summary="Validation passed",
        )
    )
    step_index += 1

    # 8. Build
    steps.append(
        _make_step(
            step_index,
            obs_type="validation.result",
            obs_summary={"passed": True},
            action_type="build.export",
            action_normalized=("build.export", "invoke", "project", "", ""),
            action_args={"targetProfile": "sap-cloud-integration-2026-07"},
            result_status="applied",
            result_summary="Build successful",
        )
    )

    # Generate requirement description + normalized requirement
    requirement = _generate_requirement_description(ir)
    normalized = _normalize_requirement_from_ir(ir, requirement)

    # Compute reward (seed artifacts: no deployment, no runtime)
    reward = compute_reward(
        completion=True,
        test_pass_rate=1.0,
        has_security_errors=False,
        corrections=0,
        total_steps=len(steps),
        deployment_state=None,
        runtime_stability=None,
    )

    return EngineeringTrajectory(
        metadata=TrajectoryMetadata(
            id=f"seed-{flow_id}",
            projectId=project_id,
            taskId=f"seed-{flow_id}",
            baseRevision="seed",
            startedAt=time.time(),
        ),
        spec=TrajectorySpec(
            query=TrajectoryQuery(
                raw=requirement,
                normalized=normalized.to_dict(),
            ),
            steps=steps,
            outcome=TrajectoryOutcome(
                status="success",
                reward=reward.to_dict(),
            ),
        ),
    )


def _make_step(
    index: int,
    obs_type: str,
    obs_summary: dict[str, Any],
    action_type: str,
    action_normalized: tuple[str, ...],
    action_args: dict[str, Any],
    result_status: str,
    result_summary: str,
) -> TrajectoryStep:
    """Build a TrajectoryStep with observation + action + result."""
    import hashlib
    import json

    args_digest = hashlib.sha256(
        json.dumps(action_args, sort_keys=True, default=str).encode()
    ).hexdigest()

    return TrajectoryStep(
        index=index,
        observation=ObservationRecord(
            type=obs_type,
            fingerprint=hashlib.sha256(
                json.dumps(obs_summary, sort_keys=True, default=str).encode()
            ).hexdigest(),
            summary=obs_summary,
        ),
        action=ActionRecord(
            type=action_type,
            normalized=tuple(str(x) for x in action_normalized),
            argumentsDigest=args_digest,
        ),
        result=ResultRecord(
            status=result_status,
            summary=result_summary,
        ),
    )


def _topological_sort(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Sort nodes in topological order based on edges."""
    node_map = {n.get("id"): n for n in nodes if n.get("id")}
    # Build adjacency list
    deps: dict[str, set[str]] = {nid: set() for nid in node_map}
    for edge in edges:
        from_id = edge.get("from", "")
        to_id = edge.get("to", "")
        if to_id in deps:
            deps[to_id].add(from_id)

    # Kahn's algorithm
    result: list[dict] = []
    visited: set[str] = set()

    def visit(nid: str):
        if nid in visited or nid not in node_map:
            return
        visited.add(nid)
        for dep in deps.get(nid, []):
            visit(dep)
        result.append(node_map[nid])

    for nid in node_map:
        visit(nid)

    # If topo sort fails (cycles), fall back to original order
    if len(result) != len(nodes):
        return nodes
    return result


def _generate_requirement_description(ir: dict) -> str:
    """Generate a natural-language requirement from the IR structure."""
    spec = ir.get("spec", {})
    nodes = spec.get("nodes", [])
    entrypoints = spec.get("entrypoints", [])

    # Extract sender type
    sender_type = "unknown"
    if entrypoints:
        sender_type = entrypoints[0].get("type", "sender.http")
    elif nodes:
        for n in nodes:
            if n.get("type", "").startswith("sender"):
                sender_type = n["type"]
                break

    # Extract receiver type
    receiver_type = "unknown"
    for n in reversed(nodes):
        if n.get("type", "").startswith("receiver"):
            receiver_type = n["type"]
            break

    # Extract processing steps
    processing = []
    for n in nodes:
        ntype = n.get("type", "")
        if not ntype.startswith("sender") and not ntype.startswith("receiver"):
            processing.append(ntype)

    parts = [f"Create an integration flow that receives via {sender_type}"]
    if processing:
        parts.append(f"processes with {', '.join(processing)}")
    parts.append(f"and sends to {receiver_type}")
    return ", ".join(parts) + "."


def _normalize_requirement_from_ir(ir: dict, raw: str) -> NormalizedRequirement:
    """Extract a NormalizedRequirement from the IR structure."""
    spec = ir.get("spec", {})
    nodes = spec.get("nodes", [])
    entrypoints = spec.get("entrypoints", [])

    # Determine intent
    intent = "create-flow"

    # Determine protocols
    source_protocol = None
    target_protocol = None
    for ep in entrypoints:
        ep_type = ep.get("type", "")
        if "http" in ep_type:
            source_protocol = "https"
        elif "sftp" in ep_type:
            source_protocol = "sftp"
        elif "soap" in ep_type:
            source_protocol = "soap"

    for n in reversed(nodes):
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

    # Determine operations
    operations = []
    components = []
    for n in nodes:
        ntype = n.get("type", "")
        if "validator" in ntype:
            operations.append("validate")
            components.append(ntype)
        elif "transform" in ntype or "xslt" in ntype:
            operations.append("transform")
            components.append(ntype)
        elif "script" in ntype or "groovy" in ntype:
            operations.append("transform")
            components.append(ntype)
        elif "router" in ntype:
            operations.append("route")
            components.append(ntype)
        elif "filter" in ntype:
            operations.append("filter")
            components.append(ntype)
        elif "splitter" in ntype:
            operations.append("split")
            components.append(ntype)
        elif "converter" in ntype or "json-to-xml" in ntype or "xml-to-json" in ntype:
            operations.append("transform")
            components.append(ntype)
        elif ntype.startswith("sender") or ntype.startswith("receiver"):
            components.append(ntype)

    # Archetype
    archetype = None
    if source_protocol and target_protocol:
        archetype = f"{source_protocol}-to-{target_protocol}"

    return NormalizedRequirement(
        intent=intent,
        archetype=archetype,
        source_protocol=source_protocol,
        target_protocol=target_protocol,
        operations=list(dict.fromkeys(operations)),  # dedupe, preserve order
        components=list(dict.fromkeys(components)),
        constraints=["must-have-error-handling", "no-secrets-inline"],
        confidence=0.9,
        raw=raw,
    )


__all__ = ["synthesize_expert_trajectory"]
