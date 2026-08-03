# `services/model-gateway` — LLM routing + redaction (Phase 3)

> **Status: SUBSTANTIALLY COMPLETE.**
> Python implementation at `services/model-gateway-python/` (ADR-PY-004). 43 tests.
> This directory is the Kotlin production target (OW-002).

The model gateway routes LLM calls to configured providers with:

- **Redaction** — strips secrets before forwarding to LLM (Bearer tokens, API keys, passwords, PEM keys, tenant URLs)
- **Token budgets** — per-project per-day limits (default 2M, HTTP 429 when exhausted)
- **Circuit breaker** — 5 failures → open, 60s reset (HTTP 503 when open)
- **Prompt-injection defense** — system prompt with 6 security rules per spec §16.3
- **Multi-provider** — Anthropic, OpenAI, Ollama, vLLM, Azure OpenAI

The Python prototype's 43 tests will be translated to Kotlin.

Spec ref: §5.1, §12.7 (Model Gateway Configuration).
