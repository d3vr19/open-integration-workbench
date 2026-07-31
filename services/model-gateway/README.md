# `services/model-gateway` — LLM routing + redaction (Phase 3)

> **Status: NOT YET IMPLEMENTED.**
> See `DEVELOPMENT_LOG.md` → Open Work item OW-004.

When implemented, this will route LLM calls to configured providers
(Anthropic, OpenAI, Ollama, vLLM, Azure) with:

- Per-project token budgets (spec §12.7)
- Circuit breaker
- Redaction of credentialRef values, authorization headers, tenant URLs
- Prompt-injection defense (untrusted-data framing)
- Local model option (Ollama / vLLM) for offline mode

**The model gateway MUST NEVER receive secret values** (spec §12.7).

Spec ref: §5.1, §12.7 (Model Gateway Configuration).
