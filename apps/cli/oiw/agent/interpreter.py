"""LLM-driven requirement interpreter (WP-04 Task 1).

Replaces the keyword-matching `interpret_requirement()` in
`apps/server-python-prototype/oiw_server/agent.py` with an LLM call
through the model gateway. The LLM produces a structured
`NormalizedRequirement` (intent, archetype, protocols, operations,
components, constraints, confidence).

Fallback path: if the gateway is unreachable (no API key, network down,
health check fails), the interpreter falls back to the existing keyword
matcher and emits warning OIW-W014.

Spec refs: §14 (LLM & Agent Architecture), §16.3 (Prompt-Injection
Boundary — system prompt defends against instructions in project files).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .context import ProjectContext
from .gateway_client import ChatResponse, ModelGatewayClient

# Warning code emitted when the LLM is unavailable and we fall back.
OIW_W014 = "OIW-W014: LLM interpreter unavailable; using keyword fallback. Install an API key for full interpretation."


@dataclass
class NormalizedRequirement:
    """Structured interpretation of a natural-language requirement.

    Field names match the JSON schema in
    `apps/cli/oiw/agent/prompts/interpreter.md`.
    """

    intent: str  # create-flow | modify-flow | fix-flow | add-test | refactor
    archetype: str | None = None
    source_protocol: str | None = None
    target_protocol: str | None = None
    operations: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    confidence: float = 0.0
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_system_prompt() -> str:
    """Load the interpreter system prompt from the prompts/ directory."""
    p = Path(__file__).parent / "prompts" / "interpreter.md"
    return p.read_text(encoding="utf-8")


def _build_interpretation_prompt(raw_text: str, project_context: ProjectContext) -> str:
    """Build the user-side prompt: requirement + project context."""
    return (
        f"## Requirement\n{raw_text}\n\n"
        f"## Project context\n{project_context.to_prompt_context()}\n\n"
        "## Task\n"
        "Produce a structured JSON interpretation per the system prompt schema. "
        "Output JSON only."
    )


def _parse_llm_response(content: str | None, raw_text: str) -> NormalizedRequirement:
    """Parse the LLM's JSON response into a NormalizedRequirement.

    Defensive: strips markdown fences, tolerates extra keys, falls back
    to a low-confidence general intent if parsing fails entirely.
    """
    if not content:
        return NormalizedRequirement(intent="general", raw=raw_text, confidence=0.0)
    # Strip ```json ... ``` fences if present
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find the first {...} block
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return NormalizedRequirement(intent="general", raw=raw_text, confidence=0.1)
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return NormalizedRequirement(intent="general", raw=raw_text, confidence=0.1)

    # Map camelCase keys to snake_case (the LLM may use either)
    def _get(key_camel: str, key_snake: str | None = None, default: Any = None) -> Any:
        return data.get(key_camel) or data.get(key_snake or key_camel, default)

    return NormalizedRequirement(
        intent=_get("intent", default="general"),
        archetype=_get("archetype"),
        source_protocol=_get("sourceProtocol", "source_protocol"),
        target_protocol=_get("targetProtocol", "target_protocol"),
        operations=_get("operations", default=[]) or [],
        components=_get("components", default=[]) or [],
        constraints=_get("constraints", default=[]) or [],
        confidence=float(_get("confidence", default=0.5) or 0.5),
        raw=raw_text,
    )


async def interpret_requirement(
    raw_text: str,
    project_context: ProjectContext,
    gateway: ModelGatewayClient,
) -> NormalizedRequirement:
    """Send requirement to LLM, receive structured interpretation.

    Raises:
        RuntimeError: if the gateway call fails (caller should fall back).
    """
    messages = [
        {"role": "system", "content": _load_system_prompt()},
        {"role": "user", "content": _build_interpretation_prompt(raw_text, project_context)},
    ]
    response: ChatResponse = await gateway.chat(
        messages=messages,
        response_format={"type": "json_object"},
        max_tokens=1024,
        temperature=0.1,
    )
    return _parse_llm_response(response.content, raw_text)


# ---------------------------------------------------------------------------
# Keyword fallback (spec §14: LLM-unavailable path)
# ---------------------------------------------------------------------------


def interpret_requirement_fallback(raw_text: str) -> NormalizedRequirement:
    """Keyword-matching interpreter, used when the LLM is unavailable.

    Mirrors the logic in
    `apps/server-python-prototype/oiw_server/agent.py::interpret_requirement`
    but produces a `NormalizedRequirement` with the full WP-04 field set
    (components, constraints, confidence).
    """
    text = raw_text.lower()

    # Intent detection
    intent = "general"
    if "validation" in text or ("validate" in text and "add" in text):
        intent = "modify-flow"
    elif "test" in text and ("add" in text or "create" in text):
        intent = "add-test"
    elif any(w in text for w in ["fix", "broken", "timeout", "times out", "error"]):
        intent = "fix-flow"
    elif any(w in text for w in ["modify", "change", "update"]):
        intent = "modify-flow"
    elif any(w in text for w in ["create", "new", "build a flow"]):
        intent = "create-flow"

    # Protocols
    protocols = {
        "https": ["http", "https", "rest", "api"],
        "sftp": ["sftp", "file", "csv"],
        "soap": ["soap", "xml"],
        "odata": ["odata"],
    }
    detected: set[str] = set()
    for proto, keywords in protocols.items():
        if any(kw in text for kw in keywords):
            detected.add(proto)
    source_protocol = sorted(detected)[0] if detected else None
    target_protocol = sorted(detected)[-1] if len(detected) > 1 else None

    # Operations
    op_keywords = {
        "validate": ["validate", "validation", "schema"],
        "transform": ["transform", "mapping", "xslt", "convert"],
        "route": ["route", "router", "routing", "branch"],
        "filter": ["filter"],
        "split": ["split", "splitter"],
        "gather": ["gather", "aggregate"],
        "encode": ["encode", "base64"],
        "log": ["log"],
    }
    operations = [op for op, kws in op_keywords.items() if any(kw in text for kw in kws)]

    # Components (only those mentioned or implied)
    components: list[str] = []
    if "validation" in text or "validate" in text or "schema" in text:
        components.append("validator.json-schema")
    if "script" in text or "groovy" in text:
        components.append("script.groovy")
    if "transform" in text or "mapping" in text or "xslt" in text:
        components.append("transform.xslt")
    # WP-08 PR-8: recognize JSON↔XML converters from natural language
    if ("json" in text and "xml" in text) or "json to xml" in text or "json-to-xml" in text:
        components.append("converter.json-to-xml")
    if (
        ("xml" in text and "json" in text and "to json" in text)
        or "xml to json" in text
        or "xml-to-json" in text
    ):
        components.append("converter.xml-to-json")
    # WP-08 PR-8: recognize content modifier from header/property manipulation
    if any(
        kw in text
        for kw in ["header", "correlation id", "property", "content modifier", "set header", "set property"]
    ):
        components.append("modifier.content")
    if source_protocol == "https" or "rest" in text or "api" in text:
        components.append("sender.http")
    if "receiver" in text or "send to" in text or "forward" in text or "forwards" in text:
        components.append("receiver.http")
    # Directive names a target URL with fetch/get language ("fetches X from
    # https://...") — that IS a receiver call even without the word receiver.
    if (
        any(kw in text for kw in ["fetch", "call ", "retrieve", "get from", "query"])
        and ("http://" in text or "https://" in text)
        and "receiver.http" not in components
    ):
        components.append("receiver.http")
    if "timeout" in text:
        components.append("receiver.http")
    # WP-08 PR-8: recognize log.message from error handling / logging context
    if (
        any(kw in text for kw in ["log", "error handling", "error subprocess", "exception"])
        and "log.message" not in components
    ):
        components.append("log.message")
    # WP-08 PR-8: recognize router from routing/branching language
    if any(kw in text for kw in ["route", "router", "routing", "branch"]):
        components.append("router.content-based")
    # WP-08 PR-8: recognize filter from filtering language
    if "filter" in text:
        components.append("filter")

    # Archetype
    archetype = None
    if source_protocol and target_protocol:
        archetype = f"{source_protocol}-to-{target_protocol}"
    elif "api-to-erp" in text or "erp" in text:
        archetype = "api-to-erp"
    elif "file-to-api" in text:
        archetype = "file-to-api"

    # Constraints (default: every flow must have error handling, no secrets)
    constraints = ["must-have-error-handling", "no-secrets-inline"]

    # Confidence: keyword matcher is reasonably confident for explicit intents,
    # low for ambiguous ones.
    confidence = 0.7 if intent != "general" else 0.3

    return NormalizedRequirement(
        intent=intent,
        archetype=archetype,
        source_protocol=source_protocol,
        target_protocol=target_protocol,
        operations=operations,
        components=components,
        constraints=constraints,
        confidence=confidence,
        raw=raw_text,
    )


__all__ = [
    "NormalizedRequirement",
    "interpret_requirement",
    "interpret_requirement_fallback",
    "OIW_W014",
]
