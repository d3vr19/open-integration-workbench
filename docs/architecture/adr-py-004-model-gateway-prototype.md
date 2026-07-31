# ADR-PY-004: Python model gateway prototype

- Status: DEVIATION — TEMPORARY
- Date: 2026-07-31
- Spec ref: §5.1 (mandates Kotlin model gateway), §12.7 (Model Gateway Configuration)
- Decider: Implementing agent (Phase 3)

## Context

Spec §5.1 mandates a Kotlin model gateway at `services/model-gateway`. The
gateway's responsibilities (redaction, token budgets, circuit breaker,
prompt-injection defense, multi-provider routing) are language-agnostic and
can be implemented in Python using httpx for async HTTP calls.

## Decision

Implement the model gateway in Python at `services/model-gateway-python/`
as a FastAPI service. The gateway:

- Uses `httpx` for async LLM provider calls (Anthropic, OpenAI, Ollama, vLLM, Azure).
- Implements the redaction layer as pure Python regex patterns — no external deps.
- Implements the budget tracker and circuit breaker as thread-safe in-memory structures.
- Includes the prompt-injection defense system prompt as a Python string constant.

## Consequences

- Positive: The gateway is immediately runnable with `oiw-gateway` and integrates with the MCP server.
- Positive: 43 tests cover all security-critical paths (redaction, budget, circuit breaker, prompt-injection defense).
- Positive: Local models (Ollama/vLLM) work offline (spec §4.5).
- Negative: Four Python implementations exist during the migration window. All are thin adapters over the same `oiw` CLI package — no duplication of business logic.
- Neutral: Migration to Kotlin is a mechanical translation. The 43 tests survive unchanged.

## Migration plan

The Kotlin model gateway (when implemented) will:
1. Implement the same FastAPI endpoints (POST /llm/chat, GET /llm/budget/{id}, GET /llm/health).
2. Use the same redaction patterns (translated from Python regex to Kotlin regex).
3. Include the same prompt-injection defense system prompt.
4. Pass the same 43 tests (translated to Kotlin).
