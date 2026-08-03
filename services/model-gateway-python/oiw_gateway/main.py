"""Model gateway FastAPI application.

Spec ref: §12.7 (Model Gateway Configuration), §16.3 (Prompt-Injection Boundary).

Endpoints:
  POST /api/v1/llm/chat          — chat completion with redaction + budget + circuit breaker
  GET  /api/v1/llm/budget/{id}   — get token budget status for a project
  GET  /api/v1/llm/health        — health check
  GET  /api/v1/llm/providers     — list configured providers
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import __version__
from .budget import BudgetTracker, CircuitBreaker
from .prompts import build_system_prompt
from .providers import call_provider, load_provider_config
from .redaction import redact_messages

app = FastAPI(
    title="OIW Model Gateway",
    description="LLM routing with redaction, token budgets, and prompt-injection defense. Spec §12.7.",
    version=__version__,
)

# Global state — in production these would be injected via dependency
_budget = BudgetTracker(max_tokens_per_day=int(os.environ.get("OIW_MAX_TOKENS_PER_DAY", "2000000")))
_breaker = CircuitBreaker(
    failure_threshold=int(os.environ.get("OIW_CB_FAILURE_THRESHOLD", "5")),
    reset_timeout_seconds=int(os.environ.get("OIW_CB_RESET_TIMEOUT", "60")),
)


class ChatRequest(BaseModel):
    """Chat completion request."""

    projectId: str
    messages: list[dict[str, Any]]
    systemPrompt: str | None = None
    provider: str | None = None
    estimatedTokens: int = 1000


class ChatResponse(BaseModel):
    """Chat completion response."""

    content: str
    provider: str
    model: str
    tokensUsed: int
    redactions: list[str]
    budgetRemaining: int
    finishReason: str


class BudgetResponse(BaseModel):
    projectId: str
    tokensUsedToday: int
    maxTokensPerDay: int
    remaining: int
    requestsToday: int
    exhausted: bool


@app.get("/api/v1/llm/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/api/v1/llm/providers")
def list_providers() -> dict:
    """List the default provider and available alternatives."""
    default = load_provider_config()
    return {
        "defaultProvider": default.name,
        "model": default.model,
        "providerType": default.provider_type,
        "apiKeyConfigured": bool(default.api_key_env and os.environ.get(default.api_key_env)),
        "baseUrl": default.base_url,
    }


@app.post("/api/v1/llm/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Send a chat completion request through the gateway.

    Pipeline:
      1. Check token budget — reject if exhausted
      2. Check circuit breaker — reject if open
      3. Redact secrets from messages (spec §12.7)
      4. Build system prompt with prompt-injection defense (spec §16.3)
      5. Call the LLM provider
      6. Record token usage
      7. Return result with redaction report
    """
    # 1. Budget check
    if not _budget.check(req.projectId, req.estimatedTokens):
        status = _budget.get_status(req.projectId)
        raise HTTPException(
            status_code=429,
            detail=f"token budget exhausted for project '{req.projectId}': "
            f"{status.tokens_used_today}/{status.max_tokens_per_day} tokens used today",
        )

    # 2. Load provider config
    config = load_provider_config(req.provider)

    # 3. Circuit breaker check
    if not _breaker.can_call(config.name):
        state = _breaker.get_state(config.name)
        raise HTTPException(
            status_code=503,
            detail=f"circuit breaker open for provider '{config.name}' (failures={state.failure_count})",
        )

    # 4. Redact secrets from messages (spec §12.7)
    redacted_messages, redactions = redact_messages(req.messages)

    # 5. Build system prompt with prompt-injection defense (spec §16.3)
    system_prompt = build_system_prompt(req.systemPrompt)

    # 6. Call the provider
    try:
        result = await call_provider(config, redacted_messages, system_prompt)
        _breaker.record_success(config.name)
    except Exception as exc:
        _breaker.record_failure(config.name)
        raise HTTPException(
            status_code=502,
            detail=f"LLM provider call failed: {type(exc).__name__}: {exc}",
        ) from exc

    # 7. Record token usage
    _budget.record(req.projectId, result.tokens_used)

    budget = _budget.get_status(req.projectId)
    return ChatResponse(
        content=result.content,
        provider=result.provider,
        model=result.model,
        tokensUsed=result.tokens_used,
        redactions=redactions,
        budgetRemaining=budget.remaining,
        finishReason=result.finish_reason,
    )


@app.get("/api/v1/llm/budget/{project_id}", response_model=BudgetResponse)
def get_budget(project_id: str) -> BudgetResponse:
    """Get the token budget status for a project."""
    status = _budget.get_status(project_id)
    return BudgetResponse(
        projectId=status.project_id,
        tokensUsedToday=status.tokens_used_today,
        maxTokensPerDay=status.max_tokens_per_day,
        remaining=status.remaining,
        requestsToday=status.requests_today,
        exhausted=status.exhausted,
    )


def main() -> None:
    """Entry point for the oiw-gateway console script."""
    import uvicorn

    port = int(os.environ.get("OIW_GATEWAY_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
