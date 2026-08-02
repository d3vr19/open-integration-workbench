"""Model gateway client — async OpenAI-compatible HTTP client.

Spec ref: §14 (LLM & Agent Architecture), §12.7 (Model Gateway Configuration).
WP-04 Task 5.

The agent pipeline talks to the model gateway through this client. The
gateway itself lives in `services/model-gateway-python/` and exposes an
OpenAI-compatible chat completions endpoint plus a /health probe.

Design notes:
- The client is intentionally thin: no retry, no streaming. Bounded
  correction lives in the executor (Task 3), not here.
- If the gateway is unreachable, `health()` returns False and the
  orchestrator falls back to the keyword interpreter + hardcoded
  planner with warning OIW-W014.
- All requests carry the project's API key (if configured). The
  gateway does the actual redaction server-side (spec §15.17).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx


DEFAULT_BASE_URL = os.environ.get("OIW_MODEL_GATEWAY_URL", "http://127.0.0.1:8080")
DEFAULT_TIMEOUT_SECONDS = 60.0


@dataclass
class ChatResponse:
    """Result of a single chat completion call.

    Fields mirror the OpenAI Chat Completions response shape (the subset
    the agent pipeline actually consumes).
    """

    content: str | None
    tool_calls: list[dict[str, Any]] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    provider: str | None = None
    model: str | None = None
    finish_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "tool_calls": self.tool_calls,
            "usage": self.usage,
            "provider": self.provider,
            "model": self.model,
            "finishReason": self.finish_reason,
        }


class ModelGatewayClient:
    """Async client for the OIW model gateway.

    The gateway is FastAPI (see services/model-gateway-python/oiw_gateway/main.py)
    and exposes:
      GET  /api/v1/llm/health       -> {"status": "ok", ...}
      POST /api/v1/llm/chat         -> ChatResponse payload
      GET  /api/v1/llm/budget/{id}  -> budget snapshot

    This client only consumes /health and /chat. Budget enforcement and
    redaction happen server-side; the agent does not need to know the
    underlying provider (anthropic, openai, ollama, ...).
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        project_id: str = "default",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key or os.environ.get("OIW_MODEL_GATEWAY_KEY")
        self.project_id = project_id
        self._http = httpx.AsyncClient(timeout=timeout)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        system_prompt: str | None = None,
    ) -> ChatResponse:
        """Send a chat completion request and return the parsed response.

        Args:
            messages: OpenAI-style message list.
            tools: Optional list of tool/function schemas (function-calling).
            response_format: Optional `{"type": "json_object"}` to force JSON.
            max_tokens: Cap on response tokens.
            temperature: Sampling temperature.
            system_prompt: Optional override for the gateway's default system
                prompt. The gateway will still prepend its redaction +
                injection-defense preamble.

        Returns:
            ChatResponse with content (and tool_calls if the model produced
            any).

        Raises:
            httpx.HTTPStatusError: on non-2xx response.
            httpx.RequestError: on network failure.
        """
        payload: dict[str, Any] = {
            "projectId": self.project_id,
            "messages": messages,
            "estimatedTokens": max_tokens,
        }
        if system_prompt is not None:
            payload["systemPrompt"] = system_prompt
        if tools:
            # The gateway accepts an OpenAI-style `tools` field alongside
            # the standard chat payload; provider adapters translate this
            # into provider-specific function-calling formats.
            payload["tools"] = tools
            payload["toolChoice"] = "auto"
        if response_format:
            payload["responseFormat"] = response_format
        payload["maxTokens"] = max_tokens
        payload["temperature"] = temperature

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        resp = await self._http.post(
            f"{self.base_url}/api/v1/llm/chat",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

        # The gateway returns a ChatResponse-shaped payload. Normalize it
        # into our dataclass so callers don't have to deal with raw JSON.
        return ChatResponse(
            content=data.get("content"),
            tool_calls=data.get("tool_calls"),
            usage=data.get("usage", {}),
            provider=data.get("provider"),
            model=data.get("model"),
            finish_reason=data.get("finishReason"),
        )

    async def health(self) -> bool:
        """Return True iff the gateway is reachable and reports healthy.

        Used by the orchestrator to decide between LLM and keyword fallback.
        Never raises — a network failure is reported as `False`.
        """
        try:
            resp = await self._http.get(
                f"{self.base_url}/api/v1/llm/health",
                timeout=5.0,
            )
            return resp.status_code == 200 and resp.json().get("status") == "ok"
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "ModelGatewayClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()


__all__ = ["ModelGatewayClient", "ChatResponse", "DEFAULT_BASE_URL"]
