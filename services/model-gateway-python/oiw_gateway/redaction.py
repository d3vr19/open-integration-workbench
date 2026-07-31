"""Redaction layer — strips secrets from LLM context.

Spec ref: §12.7 (redaction), §4.6 (secrets never enter source control),
§16.3 (prompt-injection boundary).

The model gateway MUST NEVER receive secret values. This module scans
outgoing LLM context (system prompt + messages) and redacts:
  - credentialRef values (anything that looks like a password, API key, token)
  - Authorization headers (Bearer tokens, Basic auth)
  - Tenant URLs (replaced with placeholder <tenant-url>)
  - Private key material (PEM blocks)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class RedactionResult:
    """Result of redacting a context."""

    redacted_text: str
    redactions: list[str] = field(default_factory=list)

    @property
    def redaction_count(self) -> int:
        return len(self.redactions)


# Patterns that look like secrets (spec §14.1 OIW-E002, extended for LLM context)
_SECRET_PATTERNS = [
    # Bearer tokens
    (re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}"), "<redacted-bearer-token>"),
    # Basic auth headers
    (re.compile(r"Authorization:\s*Basic\s+[A-Za-z0-9+/=]{16,}"), "Authorization: Basic <redacted>"),
    # API keys (common formats: api_key, api-key, apikey, apiKey)
    (re.compile(r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}['\"]?"), "<redacted-api-key>"),
    # Password assignments (password = "x", password: "x", Password: x)
    (re.compile(r"(?i)password\s*[:=]\s*['\"]?([^'\"\s]{6,})['\"]?"), "password=<redacted>"),
    # Secret assignments
    (re.compile(r"(?i)secret\s*[:=]\s*['\"]([^'\"]{6,})['\"]"), "secret=<redacted>"),
    # Token assignments
    (re.compile(r"(?i)token\s*[:=]\s*['\"]([^'\"]{6,})['\"]"), "token=<redacted>"),
    # Private key blocks (PEM)
    (
        re.compile(
            r"-----BEGIN\s+[A-Z\s]*PRIVATE\s+KEY-----.*?-----END\s+[A-Z\s]*PRIVATE\s+KEY-----", re.DOTALL
        ),
        "<redacted-private-key>",
    ),
    # credentialRef values that look like actual secrets (long strings)
    (
        re.compile(r"credentialRef\s*[:=]\s*['\"]([A-Za-z0-9+/=_\-]{50,})['\"]"),
        "credentialRef=<redacted-looks-like-secret>",
    ),
]

# Tenant URL pattern — replace actual tenant URLs with placeholder
_TENANT_URL_PATTERN = re.compile(
    r"https?://[a-zA-Z0-9\-]+\.integration\.sap[a-zA-Z0-9\-]*\.[a-zA-Z]{2,}/?[a-zA-Z0-9\-./?=&]*"
)

# SAP tenant hostnames (e.g., xxx.integration.sap-cloud.xxx)
_SAP_TENANT_HOST_PATTERN = re.compile(
    r"https?://[a-zA-Z0-9\-]+\.sap[a-zA-Z0-9\-]*\.[a-zA-Z]{2,}[a-zA-Z0-9\-./?=&]*"
)


def redact(text: str) -> RedactionResult:
    """Redact secrets from a text string.

    Spec §12.7: the model gateway MUST NEVER receive secret values.

    Args:
        text: The text to redact (system prompt, message content, etc.)

    Returns:
        RedactionResult with the redacted text and a list of what was redacted.
    """
    if not text:
        return RedactionResult(redacted_text=text)

    redacted = text
    redactions: list[str] = []

    for pattern, replacement in _SECRET_PATTERNS:
        matches = pattern.findall(redacted)
        if matches:
            count = len(matches) if isinstance(matches, list) else 1
            redactions.append(f"{count}x {replacement}")
            redacted = pattern.sub(replacement, redacted)

    # Redact tenant URLs
    tenant_matches = _TENANT_URL_PATTERN.findall(redacted)
    if tenant_matches:
        redactions.append(f"{len(tenant_matches)}x tenant-url")
        redacted = _TENANT_URL_PATTERN.sub("<tenant-url>", redacted)
    else:
        # Fallback: redact SAP hostnames
        sap_matches = _SAP_TENANT_HOST_PATTERN.findall(redacted)
        if sap_matches:
            redactions.append(f"{len(sap_matches)}x sap-host-url")
            redacted = _SAP_TENANT_HOST_PATTERN.sub("<sap-host-url>", redacted)

    return RedactionResult(redacted_text=redacted, redactions=redactions)


def redact_messages(messages: list[dict]) -> tuple[list[dict], list[str]]:
    """Redact secrets from a list of chat messages.

    Args:
        messages: List of message dicts with 'role' and 'content' keys.

    Returns:
        Tuple of (redacted_messages, all_redactions).
    """
    redacted_messages: list[dict] = []
    all_redactions: list[str] = []

    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            result = redact(content)
            redacted_messages.append({**msg, "content": result.redacted_text})
            all_redactions.extend(result.redactions)
        elif isinstance(content, list):
            # Multi-part content (e.g., Anthropic format)
            redacted_parts: list[dict] = []
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    result = redact(part["text"])
                    redacted_parts.append({**part, "text": result.redacted_text})
                    all_redactions.extend(result.redactions)
                else:
                    redacted_parts.append(part)
            redacted_messages.append({**msg, "content": redacted_parts})
        else:
            redacted_messages.append(msg)

    return redacted_messages, all_redactions
