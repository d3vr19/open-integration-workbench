"""Message context for the local simulation runtime.

Spec ref: §9.1 (Message Context).
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any


@dataclasses.dataclass
class Attachment:
    name: str
    content_type: str
    body: bytes


@dataclasses.dataclass
class TraceEntry:
    node_id: str
    timestamp: float
    direction: str  # "enter" | "exit" | "error"
    summary: str
    body_preview: str | None = None
    headers: dict[str, Any] | None = None
    # FIGAF-style debugging capture (engine loop seam): per-step exchange
    # snapshots + timing + error typing. Optional so old traces keep loading.
    properties: dict[str, Any] | None = None
    duration_ms: int | None = None
    exception_type: str | None = None


class ExchangeStatus:
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclasses.dataclass
class SecurityContext:
    principal: str | None = None
    credential_refs_resolved: dict[str, str] = dataclasses.field(default_factory=dict)
    redacted_headers: list[str] = dataclasses.field(default_factory=lambda: ["authorization", "x-api-key"])


@dataclasses.dataclass
class MessageContext:
    """Spec §9.1.

    NOTE: In the Python prototype this runs in-process. The production runtime
    (services/runtime-worker, Phase 2) will run in a process-isolated JVM with
    seccomp + network namespace isolation per spec §9.6.
    """

    body: bytes
    content_type: str = "application/octet-stream"
    headers: dict[str, Any] = dataclasses.field(default_factory=dict)
    properties: dict[str, Any] = dataclasses.field(default_factory=dict)
    attachments: list[Attachment] = dataclasses.field(default_factory=list)
    variables: dict[str, Any] = dataclasses.field(default_factory=dict)
    exchange_status: str = ExchangeStatus.RUNNING
    exception: BaseException | None = None
    trace: list[TraceEntry] = dataclasses.field(default_factory=list)
    security_context: SecurityContext = dataclasses.field(default_factory=SecurityContext)

    # Outbound calls captured during this exchange (for assertions)
    outbound_calls: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    def redacted_headers(self) -> dict[str, Any]:
        """Return headers with sensitive values redacted (spec §9.2 step 9)."""
        out = {}
        for k, v in self.headers.items():
            if k.lower() in self.security_context.redacted_headers:
                out[k] = "<redacted>"
            else:
                out[k] = v
        return out

    def add_trace(self, node_id: str, direction: str, summary: str, **extra: Any) -> None:
        entry = TraceEntry(
            node_id=node_id,
            timestamp=time.time(),
            direction=direction,
            summary=summary,
            body_preview=extra.get("body_preview"),
            headers=extra.get("headers"),
            properties=extra.get("properties"),
            duration_ms=extra.get("duration_ms"),
            exception_type=extra.get("exception_type"),
        )
        self.trace.append(entry)

    def record_outbound(
        self, target: str, method: str, url: str, body: bytes, headers: dict[str, Any]
    ) -> None:
        self.outbound_calls.append(
            {
                "target": target,
                "method": method,
                "url": url,
                "body": body,
                "headers": dict(headers),
            }
        )
