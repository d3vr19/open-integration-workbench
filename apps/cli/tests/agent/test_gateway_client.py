"""Tests for the model gateway client (WP-04 Task 5)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from oiw.agent.gateway_client import ChatResponse, ModelGatewayClient


class FakeTransport(httpx.AsyncBaseTransport):
    """httpx transport that returns canned responses for testing."""

    def __init__(self, routes: dict[str, dict[str, Any]]):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        # Match by method + path prefix
        key = f"{request.method} {request.url.path}"
        for route_key, response in self.routes.items():
            route_path = route_key.split(" ", 1)[1] if " " in route_key else ""
            route_method = route_key.split(" ", 1)[0]
            if (
                key == route_key or request.url.path.startswith(route_path)
            ) and request.method == route_method:
                return httpx.Response(
                    status_code=response.get("status", 200),
                    json=response.get("json"),
                    text=response.get("text"),
                )
        return httpx.Response(status_code=404, text="not found")


@pytest.mark.asyncio
async def test_gateway_chat_success() -> None:
    """Mock server returns valid response — ChatResponse.content populated."""
    routes = {
        "GET /api/v1/llm/health": {"json": {"status": "ok", "version": "0.1.0"}},
        "POST /api/v1/llm/chat": {
            "json": {
                "content": '{"intent": "create-flow"}',
                "provider": "anthropic",
                "model": "claude-sonnet-4",
                "usage": {"total_tokens": 100},
                "finishReason": "stop",
            }
        },
    }
    transport = FakeTransport(routes)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        # Inject into our client
        client = ModelGatewayClient(base_url="http://test", project_id="p1")
        client._http = http
        # Health
        assert await client.health() is True
        # Chat
        resp = await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            response_format={"type": "json_object"},
            max_tokens=512,
        )
        assert isinstance(resp, ChatResponse)
        assert resp.content == '{"intent": "create-flow"}'
        assert resp.provider == "anthropic"
        assert resp.usage["total_tokens"] == 100


@pytest.mark.asyncio
async def test_gateway_chat_with_tools() -> None:
    """Mock server returns tool_calls — ChatResponse.tool_calls populated."""
    routes = {
        "GET /api/v1/llm/health": {"json": {"status": "ok"}},
        "POST /api/v1/llm/chat": {
            "json": {
                "content": None,
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "flow.patch", "arguments": '{"projectId":"p"}'}}
                ],
                "usage": {},
                "finishReason": "tool_calls",
            }
        },
    }
    transport = FakeTransport(routes)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        client = ModelGatewayClient(base_url="http://test")
        client._http = http
        resp = await client.chat(
            messages=[{"role": "user", "content": "plan"}],
            tools=[{"type": "function", "function": {"name": "flow.patch", "parameters": {}}}],
        )
        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0]["function"]["name"] == "flow.patch"


@pytest.mark.asyncio
async def test_gateway_unavailable_returns_false_health() -> None:
    """No server running — health() returns False, does not raise."""
    client = ModelGatewayClient(base_url="http://127.0.0.1:1")  # port 1 should be closed
    # Use a very short timeout to fail fast
    client._http = httpx.AsyncClient(timeout=0.5)
    assert await client.health() is False
    await client.aclose()


@pytest.mark.asyncio
async def test_gateway_chat_includes_authorization_header() -> None:
    """When api_key is set, the Authorization header is sent."""
    routes = {
        "GET /api/v1/llm/health": {"json": {"status": "ok"}},
        "POST /api/v1/llm/chat": {"json": {"content": "ok", "usage": {}}},
    }
    transport = FakeTransport(routes)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        client = ModelGatewayClient(base_url="http://test", api_key="sk-test-123")
        client._http = http
        await client.chat(messages=[{"role": "user", "content": "hi"}])
        # The fake transport recorded the request
        chat_req = next(r for r in transport.requests if r.method == "POST")
        assert chat_req.headers.get("Authorization") == "Bearer sk-test-123"


@pytest.mark.asyncio
async def test_gateway_chat_raises_on_5xx() -> None:
    """Non-2xx response raises httpx.HTTPStatusError."""
    routes = {
        "GET /api/v1/llm/health": {"json": {"status": "ok"}},
        "POST /api/v1/llm/chat": {"status": 500, "text": "internal error"},
    }
    transport = FakeTransport(routes)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        client = ModelGatewayClient(base_url="http://test")
        client._http = http
        with pytest.raises(httpx.HTTPStatusError):
            await client.chat(messages=[{"role": "user", "content": "hi"}])
