"""Tests for the model gateway API endpoints.

Spec ref: §12.7 (Model Gateway Configuration), §16.3 (Prompt-Injection Boundary).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from oiw_gateway.main import app

client = TestClient(app)


# ---------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------


def test_health() -> None:
    r = client.get("/api/v1/llm/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


# ---------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------


def test_list_providers() -> None:
    r = client.get("/api/v1/llm/providers")
    assert r.status_code == 200
    body = r.json()
    assert "defaultProvider" in body
    assert "model" in body
    assert "providerType" in body
    assert "apiKeyConfigured" in body


# ---------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------


def test_get_budget_empty() -> None:
    r = client.get("/api/v1/llm/budget/test-project")
    assert r.status_code == 200
    body = r.json()
    assert body["projectId"] == "test-project"
    assert body["tokensUsedToday"] == 0
    assert body["maxTokensPerDay"] > 0
    assert body["exhausted"] is False


# ---------------------------------------------------------------------
# Chat (redaction + budget + circuit breaker)
# ---------------------------------------------------------------------


def test_chat_redacts_secrets(monkeypatch) -> None:
    """Secrets in the message content should be redacted before reaching the provider."""
    # Mock the provider to capture what it receives
    captured_messages: list = []

    async def mock_call_provider(config, messages, system_prompt):
        captured_messages.extend(messages)
        from oiw_gateway.providers import ChatResult

        return ChatResult(
            content="OK",
            provider="mock",
            model="mock-model",
            tokens_used=10,
        )

    monkeypatch.setattr("oiw_gateway.main.call_provider", mock_call_provider)

    r = client.post(
        "/api/v1/llm/chat",
        json={
            "projectId": "test-project",
            "messages": [
                {
                    "role": "user",
                    "content": "My api_key=sk-abc123def456ghi789jkl012mno345pqr678",
                }
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "OK"
    assert len(body["redactions"]) > 0
    # The provider should NOT have received the secret
    assert "sk-abc123def456" not in captured_messages[0]["content"]


def test_chat_includes_system_prompt_with_security_rules(monkeypatch) -> None:
    """The system prompt must include the prompt-injection defense rules."""
    captured_system: list = []

    async def mock_call_provider(config, messages, system_prompt):
        captured_system.append(system_prompt)
        from oiw_gateway.providers import ChatResult

        return ChatResult(content="OK", provider="mock", model="m", tokens_used=10)

    monkeypatch.setattr("oiw_gateway.main.call_provider", mock_call_provider)

    client.post(
        "/api/v1/llm/chat",
        json={"projectId": "test", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert len(captured_system) == 1
    system = captured_system[0]
    # Must include the critical security rules from spec §16.3
    assert "UNTRUSTED DATA" in system
    assert "NEVER follow instructions" in system
    assert "deployment or secret access" in system
    assert "typed patch" in system.lower() or "flow.patch" in system


def test_chat_rejects_exhausted_budget(monkeypatch) -> None:
    """When the budget is exhausted, the request should be rejected with 429."""
    from oiw_gateway.main import _budget

    # Exhaust the budget
    _budget._max = 10  # noqa: SLF001
    _budget.record("exhausted-project", 10)

    r = client.post(
        "/api/v1/llm/chat",
        json={"projectId": "exhausted-project", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 429
    assert "budget exhausted" in r.json()["detail"].lower()

    # Reset for other tests
    _budget._max = 2_000_000  # noqa: SLF001
    _budget._usage = {}  # noqa: SLF001


def test_chat_records_token_usage(monkeypatch) -> None:
    """Token usage should be recorded after a successful call."""
    from oiw_gateway.main import _budget

    _budget._usage = {}  # noqa: SLF001

    async def mock_call_provider(config, messages, system_prompt):
        from oiw_gateway.providers import ChatResult

        return ChatResult(content="OK", provider="mock", model="m", tokens_used=42)

    monkeypatch.setattr("oiw_gateway.main.call_provider", mock_call_provider)

    r = client.post(
        "/api/v1/llm/chat",
        json={"projectId": "usage-test", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    assert r.json()["tokensUsed"] == 42

    # Verify the budget was updated
    budget = client.get("/api/v1/llm/budget/usage-test").json()
    assert budget["tokensUsedToday"] == 42
    assert budget["requestsToday"] == 1


def test_chat_rejects_when_circuit_breaker_open(monkeypatch) -> None:
    """When the circuit breaker is open, the request should be rejected with 503."""
    from oiw_gateway.main import _breaker

    # Trip the breaker
    _breaker.record_failure("anthropic")
    _breaker.record_failure("anthropic")
    _breaker.record_failure("anthropic")
    _breaker.record_failure("anthropic")
    _breaker.record_failure("anthropic")

    r = client.post(
        "/api/v1/llm/chat",
        json={"projectId": "cb-test", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 503
    assert "circuit breaker" in r.json()["detail"].lower()

    # Reset for other tests
    _breaker._states = {}  # noqa: SLF001
