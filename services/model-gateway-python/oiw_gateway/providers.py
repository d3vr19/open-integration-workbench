"""LLM provider router.

Spec ref: §12.7 (modelGateway.providers).

Supports: Anthropic, OpenAI, Ollama, vLLM, Azure OpenAI.

Each provider is an async function that takes (messages, config) and returns
a ChatResult. The gateway selects the provider based on configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class ChatResult:
    """Result of an LLM chat completion."""

    content: str
    provider: str
    model: str
    tokens_used: int
    finish_reason: str = "stop"


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""

    name: str
    provider_type: str  # "anthropic" | "openai" | "ollama" | "vllm" | "azure"
    model: str
    api_key_env: str | None = None
    base_url: str | None = None
    max_tokens: int = 16384
    temperature: float = 0.2
    endpoint: str | None = None  # Azure-specific


def load_provider_config(provider_name: str | None = None) -> ProviderConfig:
    """Load provider config from environment variables.

    Spec §12.7: defaultProvider + providers map.

    Environment variables:
      OIW_LLM_PROVIDER   — "anthropic" | "openai" | "ollama" | "vllm" | "azure"
      OIW_LLM_MODEL      — model name
      ANTHROPIC_API_KEY  — Anthropic API key
      OPENAI_API_KEY     — OpenAI API key
      OLLAMA_URL         — Ollama base URL (default http://localhost:11434)
      VLLM_URL           — vLLM base URL
      AZURE_OPENAI_KEY   — Azure OpenAI key
      AZURE_OPENAI_ENDPOINT — Azure endpoint
    """
    provider_type = provider_name or os.environ.get("OIW_LLM_PROVIDER", "anthropic")
    model = os.environ.get("OIW_LLM_MODEL", _default_model(provider_type))

    config = ProviderConfig(
        name=provider_type,
        provider_type=provider_type,
        model=model,
    )

    if provider_type == "anthropic":
        config.api_key_env = "ANTHROPIC_API_KEY"
    elif provider_type == "openai":
        config.api_key_env = "OPENAI_API_KEY"
    elif provider_type == "ollama":
        config.base_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    elif provider_type == "vllm":
        config.base_url = os.environ.get("VLLM_URL", "http://localhost:8000/v1")
    elif provider_type == "azure":
        config.api_key_env = "AZURE_OPENAI_KEY"
        config.endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")

    return config


def _default_model(provider_type: str) -> str:
    defaults = {
        "anthropic": "claude-sonnet-4-20250514",
        "openai": "gpt-4o",
        "ollama": "qwen3:32b",
        "vllm": "meta-llama/Llama-4-Scout-17B",
        "azure": "gpt-4o",
    }
    return defaults.get(provider_type, "gpt-4o")


async def call_provider(
    config: ProviderConfig,
    messages: list[dict[str, Any]],
    system_prompt: str,
) -> ChatResult:
    """Call the configured LLM provider.

    This is the actual HTTP call to the provider API. For providers without
    an API key configured, it raises a ValueError.

    For local providers (Ollama, vLLM), the call goes to the configured base_url.
    """
    if config.provider_type == "anthropic":
        return await _call_anthropic(config, messages, system_prompt)
    if config.provider_type == "openai":
        return await _call_openai(config, messages, system_prompt)
    if config.provider_type == "ollama":
        return await _call_ollama(config, messages, system_prompt)
    if config.provider_type == "vllm":
        return await _call_vllm(config, messages, system_prompt)
    if config.provider_type == "azure":
        return await _call_azure(config, messages, system_prompt)
    raise ValueError(f"unknown provider type: {config.provider_type}")


async def _call_anthropic(
    config: ProviderConfig,
    messages: list[dict],
    system_prompt: str,
) -> ChatResult:
    api_key = os.environ.get(config.api_key_env or "ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": config.model,
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
                "system": system_prompt,
                "messages": messages,
            },
        )
        response.raise_for_status()
        data = response.json()

    content = data.get("content", [{}])[0].get("text", "")
    usage = data.get("usage", {})
    tokens_used = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    return ChatResult(
        content=content,
        provider="anthropic",
        model=config.model,
        tokens_used=tokens_used,
        finish_reason=data.get("stop_reason", "stop"),
    )


async def _call_openai(
    config: ProviderConfig,
    messages: list[dict],
    system_prompt: str,
) -> ChatResult:
    api_key = os.environ.get(config.api_key_env or "OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")

    full_messages = [{"role": "system", "content": system_prompt}] + messages
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.model,
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
                "messages": full_messages,
            },
        )
        response.raise_for_status()
        data = response.json()

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = data.get("usage", {})
    tokens_used = usage.get("total_tokens", 0)
    return ChatResult(
        content=content,
        provider="openai",
        model=config.model,
        tokens_used=tokens_used,
        finish_reason=data.get("choices", [{}])[0].get("finish_reason", "stop"),
    )


async def _call_ollama(
    config: ProviderConfig,
    messages: list[dict],
    system_prompt: str,
) -> ChatResult:
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    base_url = config.base_url or "http://localhost:11434"
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{base_url}/api/chat",
            json={
                "model": config.model,
                "messages": full_messages,
                "stream": False,
                "options": {"temperature": config.temperature},
            },
        )
        response.raise_for_status()
        data = response.json()

    content = data.get("message", {}).get("content", "")
    # Ollama doesn't always return token counts; estimate from content length
    tokens_used = data.get("eval_count", len(content) // 4)
    return ChatResult(
        content=content,
        provider="ollama",
        model=config.model,
        tokens_used=tokens_used,
        finish_reason="stop",
    )


async def _call_vllm(
    config: ProviderConfig,
    messages: list[dict],
    system_prompt: str,
) -> ChatResult:
    # vLLM uses an OpenAI-compatible API
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    base_url = config.base_url or "http://localhost:8000/v1"
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": config.model,
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
                "messages": full_messages,
            },
        )
        response.raise_for_status()
        data = response.json()

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = data.get("usage", {})
    tokens_used = usage.get("total_tokens", 0)
    return ChatResult(
        content=content,
        provider="vllm",
        model=config.model,
        tokens_used=tokens_used,
        finish_reason=data.get("choices", [{}])[0].get("finish_reason", "stop"),
    )


async def _call_azure(
    config: ProviderConfig,
    messages: list[dict],
    system_prompt: str,
) -> ChatResult:
    api_key = os.environ.get(config.api_key_env or "AZURE_OPENAI_KEY", "")
    if not api_key:
        raise ValueError("AZURE_OPENAI_KEY not set")
    endpoint = config.endpoint
    if not endpoint:
        raise ValueError("AZURE_OPENAI_ENDPOINT not set")

    full_messages = [{"role": "system", "content": system_prompt}] + messages
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{endpoint}/openai/deployments/{config.model}/chat/completions?api-version=2024-02-15-preview",
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json={
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
                "messages": full_messages,
            },
        )
        response.raise_for_status()
        data = response.json()

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = data.get("usage", {})
    tokens_used = usage.get("total_tokens", 0)
    return ChatResult(
        content=content,
        provider="azure",
        model=config.model,
        tokens_used=tokens_used,
        finish_reason=data.get("choices", [{}])[0].get("finish_reason", "stop"),
    )
