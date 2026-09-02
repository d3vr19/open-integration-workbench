"""Simulate route — run a flow with a test case and stream trace events.

Spec ref: §9.2 (Execution Engine step 8 — stream trace via WebSocket),
§21.1 (POST /projects/{id}/simulate), §21.2 (WebSocket /ws/trace).

This module exposes two things:
  1. POST /api/v1/projects/{id}/flows/{flowId}/simulate — runs the flow
     synchronously and returns the final trace + status.
  2. WebSocket /ws/trace — a client connects here, sends a simulate request,
     and receives trace events in real time as the flow executes.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from oiw.runtime.engine import execute_flow
from pydantic import BaseModel

from ..workspace import load_project

router = APIRouter(prefix="/api/v1", tags=["Simulation"])


class SimulateRequest(BaseModel):
    """Run a flow with given input. Spec §7.4 (FlowTest input shape)."""

    entrypoint: str | None = None
    body_file: str | None = None
    body_inline: str | None = None
    headers: dict[str, str] = {}
    mocks: list[dict[str, Any]] = []


class SimulateResponse(BaseModel):
    status: str
    duration_ms: int
    trace: list[dict[str, Any]]
    outbound_calls: list[dict[str, Any]]
    headers: dict[str, Any]
    properties: dict[str, Any]


@router.post(
    "/projects/{project_id}/flows/{flow_id}/simulate",
    response_model=SimulateResponse,
)
def simulate_sync(project_id: str, flow_id: str, req: SimulateRequest) -> SimulateResponse:
    """Run a flow synchronously and return the final trace.

    For real-time streaming, use the WebSocket endpoint at /ws/trace instead.
    """
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc
    try:
        flow = project.get_flow(flow_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"flow not found: {exc}") from exc

    body = _resolve_body(project.root, req)
    mocks_dict = {m["target"]: m for m in req.mocks}

    ctx = execute_flow(
        flow=flow,
        input_body=body,
        input_headers=dict(req.headers),
        resources=project.resources,
        mocks=mocks_dict,
    )

    return SimulateResponse(
        status=ctx.exchange_status,
        duration_ms=ctx.properties.get("__duration_ms__", 0),
        trace=[_trace_payload(t) for t in ctx.trace],
        outbound_calls=[
            {
                "target": c["target"],
                "method": c["method"],
                "url": c["url"],
                "body": c.get("body", b"").decode("utf-8", errors="replace")
                if isinstance(c.get("body"), bytes)
                else c.get("body"),
                "requestHeaders": c.get("headers", {}),
            }
            for c in ctx.outbound_calls
        ],
        headers=dict(ctx.headers),
        properties={k: v for k, v in ctx.properties.items() if not k.startswith("__")},
    )


def _trace_payload(t: Any) -> dict[str, Any]:
    """Full trace entry for the FIGAF-style viewer: summaries plus per-step
    body/headers/properties snapshots, durations, and error typing."""
    return {
        "node_id": t.node_id,
        "timestamp": t.timestamp,
        "direction": t.direction,
        "summary": t.summary,
        "body_preview": t.body_preview,
        "headers": t.headers,
        "properties": t.properties,
        "duration_ms": t.duration_ms,
        "exception_type": t.exception_type,
    }


# ---------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------


@router.websocket("/ws/trace")
async def simulate_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for simulation trace streaming.

    Spec §21.2: /ws/trace — simulation trace streaming.
    Spec §9.2 step 8: capture structured trace and stream via WebSocket to UI.

    Protocol:
      Client connects, then sends a JSON message:
        {
          "project_id": "order-to-s4",
          "flow_id": "order-to-s4",
          "body_inline": "...",
          "headers": {"Content-Type": "application/json"},
          "mocks": [{"target": "receiver-s4-eu", "respond": {"status": 201, "body": "..."}}]
        }

      Server responds with multiple JSON messages:
        {"type": "trace", "node_id": "...", "direction": "enter|exit|error", "summary": "...", "timestamp": ...}
        ... (one per node as it executes)
        {"type": "complete", "status": "COMPLETED|FAILED", "duration_ms": ..., "trace_count": N}

      The server handles one simulation request per connection. To run another
      simulation, the client opens a new WebSocket connection.

    Note: the prototype runs the flow synchronously in a thread pool; trace
    events are buffered and sent after the flow completes. True per-node
    streaming requires the JVM runtime worker (OW-003) which will run flows
    in a separate process with proper async trace emission.
    """
    await websocket.accept()
    try:
        msg = await websocket.receive_text()
        try:
            req = json.loads(msg)
        except json.JSONDecodeError:
            await websocket.send_json({"type": "error", "message": "invalid JSON"})
            return

        project_id = req.get("project_id")
        flow_id = req.get("flow_id")
        if not project_id or not flow_id:
            await websocket.send_json({"type": "error", "message": "project_id and flow_id are required"})
            return

        try:
            project = load_project(project_id)
            flow = project.get_flow(flow_id)
        except Exception as exc:
            await websocket.send_json({"type": "error", "message": str(exc)})
            return

        body = _resolve_body(project.root, SimulateRequest(**req))
        mocks_dict = {m["target"]: m for m in req.get("mocks", [])}

        # Collect trace events as they're produced
        collected: list[dict[str, Any]] = []

        def collect_trace(entry, ctx) -> None:
            collected.append(
                {
                    "type": "trace",
                    "node_id": entry.node_id,
                    "direction": entry.direction,
                    "summary": entry.summary,
                    "timestamp": entry.timestamp,
                    "body_preview": entry.body_preview,
                    "headers": entry.headers,
                    "properties": entry.properties,
                    "duration_ms": entry.duration_ms,
                    "exception_type": entry.exception_type,
                }
            )

        # Run the flow in a thread pool so we don't block the event loop
        loop = asyncio.get_event_loop()
        ctx = await loop.run_in_executor(
            None,
            lambda: execute_flow(
                flow=flow,
                input_body=body,
                input_headers=dict(req.get("headers", {})),
                resources=project.resources,
                mocks=mocks_dict,
                trace_callback=collect_trace,
            ),
        )

        # Stream the collected trace events to the client
        for event in collected:
            await websocket.send_json(event)

        await websocket.send_json(
            {
                "type": "complete",
                "status": ctx.exchange_status,
                "duration_ms": ctx.properties.get("__duration_ms__", 0),
                "trace_count": len(collected),
            }
        )

    except WebSocketDisconnect:
        pass


def _resolve_body(project_root, req: SimulateRequest) -> bytes:
    """Resolve the input body from body_file or body_inline."""
    if req.body_file:
        from pathlib import Path

        body_path = Path(project_root) / req.body_file
        if not body_path.exists():
            raise HTTPException(
                status_code=400,
                detail=f"body_file not found: {req.body_file}",
            )
        return body_path.read_bytes()
    if req.body_inline is not None:
        return req.body_inline.encode("utf-8")
    return b""
