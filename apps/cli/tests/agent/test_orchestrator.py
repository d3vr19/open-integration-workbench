"""Tests for the agent orchestrator (WP-04 Task 7)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from oiw.agent.gateway_client import ChatResponse, ModelGatewayClient
from oiw.agent.orchestrator import AgentResult, run_agent


@pytest.mark.asyncio
async def test_orchestrator_fallback_emits_warnings(temp_project: Path) -> None:
    """Gateway unavailable — keyword interpreter + hardcoded planner used, OIW-W014 warnings emitted."""
    # Mock the gateway's health() to return False
    gateway = AsyncMock(spec=ModelGatewayClient)
    gateway.health.return_value = False
    gateway.aclose = AsyncMock()

    result = await run_agent(
        requirement="Add JSON schema validation to order-to-s4",
        project_path=temp_project / "order-to-s4",
        mode="autonomous",
        flow_id="order-to-s4",
        gateway=gateway,
        persist_dir=temp_project / "traj",
    )
    assert result.status in {"COMPLETED", "FAILED"}  # fallback may complete or fail
    # Warning OIW-W014 emitted
    assert any("OIW-W014" in w for w in result.warnings)
    # Trajectory ID assigned
    assert result.trajectory_id.startswith("traj-")
    # Plan was produced (even if from fallback)
    assert result.plan is not None
    # Trajectory file persisted
    traj_files = list((temp_project / "traj").glob("traj-*.yaml"))
    assert len(traj_files) == 1
    loaded = yaml.safe_load(traj_files[0].read_text(encoding="utf-8"))
    assert loaded["metadata"]["projectId"] == "order-to-s4"


@pytest.mark.asyncio
async def test_orchestrator_co_pilot_rejection(temp_project: Path) -> None:
    """User rejects plan — status REJECTED, no patches applied, trajectory finalized."""

    async def reject(_plan):
        return False

    gateway = AsyncMock(spec=ModelGatewayClient)
    gateway.health.return_value = True
    gateway.chat.return_value = ChatResponse(
        content=json.dumps({
            "intent": "modify-flow",
            "operations": ["validate"],
            "components": ["validator.json-schema"],
            "confidence": 0.9,
        }),
    )
    gateway.aclose = AsyncMock()

    result = await run_agent(
        requirement="Add validation to order-to-s4",
        project_path=temp_project / "order-to-s4",
        mode="co-pilot",
        flow_id="order-to-s4",
        gateway=gateway,
        approval_callback=reject,
        persist_dir=temp_project / "traj",
    )
    assert result.status == "REJECTED"
    assert result.plan is not None
    assert result.execution is None  # no execution happened
    # Trajectory persisted with status 'rejected'
    traj_files = list((temp_project / "traj").glob("traj-*.yaml"))
    assert len(traj_files) == 1
    loaded = yaml.safe_load(traj_files[0].read_text(encoding="utf-8"))
    assert loaded["spec"]["outcome"]["status"] == "rejected"


@pytest.mark.asyncio
async def test_orchestrator_trajectory_persisted(temp_project: Path) -> None:
    """Any execution — .oiw/trajectories/traj-*.yaml exists."""
    gateway = AsyncMock(spec=ModelGatewayClient)
    gateway.health.return_value = False  # fallback path
    gateway.aclose = AsyncMock()

    await run_agent(
        requirement="Add validation to order-to-s4",
        project_path=temp_project / "order-to-s4",
        mode="autonomous",
        flow_id="order-to-s4",
        gateway=gateway,
        persist_dir=temp_project / "traj",
    )
    traj_files = list((temp_project / "traj").glob("traj-*.yaml"))
    assert len(traj_files) == 1
    loaded = yaml.safe_load(traj_files[0].read_text(encoding="utf-8"))
    assert loaded["metadata"]["id"].startswith("traj-")
    assert loaded["spec"]["query"]["raw"]  # the original requirement
    assert loaded["spec"]["query"]["normalized"]  # normalized requirement


@pytest.mark.asyncio
async def test_orchestrator_end_to_end_with_mock_gateway(temp_project: Path) -> None:
    """End-to-end: mock gateway returns valid interpretation + plan, executor applies patches."""
    head = _git_head(temp_project / "order-to-s4")

    gateway = AsyncMock(spec=ModelGatewayClient)
    gateway.health.return_value = True
    # First call: interpreter; second call: planner
    gateway.chat.side_effect = [
        # Interpreter response
        ChatResponse(content=json.dumps({
            "intent": "modify-flow",
            "operations": ["validate"],
            "components": ["validator.json-schema"],
            "confidence": 0.9,
        })),
        # Planner response — produces a flow.patch that adds a validator node
        ChatResponse(content=json.dumps({
            "steps": [
                {
                    "order": 1,
                    "tool": "flow.patch",
                    "arguments": {
                        "projectId": "order-to-s4",
                        "flowId": "order-to-s4",
                        "baseRevision": head,
                        "operations": [{
                            "op": "addNode",
                            "node": {
                                "id": "e2e-validator",
                                "type": "validator.json-schema",
                                "config": {"schema": "resources/schemas/order.schema.json"},
                                "fidelity": "compatible-subset",
                            },
                        }],
                    },
                    "rationale": "add validator",
                },
            ],
            "assumptions": [],
            "risks": [],
        })),
    ]
    gateway.aclose = AsyncMock()

    result = await run_agent(
        requirement="Add validation to order-to-s4",
        project_path=temp_project / "order-to-s4",
        mode="autonomous",
        flow_id="order-to-s4",
        gateway=gateway,
        persist_dir=temp_project / "traj",
    )
    assert result.status == "COMPLETED"
    assert result.plan is not None
    assert result.execution is not None
    assert len(result.execution.completed_steps) >= 1
    # The validator node should have been added to the flow
    import yaml as _yaml
    flow_path = temp_project / "order-to-s4" / "flows" / "order-to-s4" / "flow.yaml"
    flow_data = _yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    node_ids = [n["id"] for n in flow_data["spec"]["nodes"]]
    assert "e2e-validator" in node_ids


def _git_head(project_dir: Path) -> str:
    import subprocess
    return subprocess.run(
        ["git", "-C", str(project_dir), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


@pytest.mark.asyncio
async def test_orchestrator_reward_computed(temp_project: Path) -> None:
    """Successful execution — outcome.reward populated with structural_correctness."""
    gateway = AsyncMock(spec=ModelGatewayClient)
    gateway.health.return_value = False  # fallback
    gateway.aclose = AsyncMock()

    await run_agent(
        requirement="Add validation to order-to-s4",
        project_path=temp_project / "order-to-s4",
        mode="autonomous",
        flow_id="order-to-s4",
        gateway=gateway,
        persist_dir=temp_project / "traj",
    )
    traj_files = list((temp_project / "traj").glob("traj-*.yaml"))
    loaded = yaml.safe_load(traj_files[0].read_text(encoding="utf-8"))
    reward = loaded["spec"]["outcome"]["reward"]
    assert "structural_correctness" in reward
    assert "completion" in reward
    assert "corrections_needed" in reward
    assert "conflict_count" in reward
