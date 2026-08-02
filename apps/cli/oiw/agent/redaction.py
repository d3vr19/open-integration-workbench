"""Secret redaction for trajectory persistence (spec §15.17).

The trajectory file must never contain:
  - Bearer tokens
  - Passwords / client secrets / API keys
  - PEM-encoded private keys
  - SAP-internal hostnames

This module is a *defensive* layer: the model gateway already redacts
prompts before they reach the provider (see
services/model-gateway-python/oiw_gateway/redaction.py). This layer
catches secrets that slip into:
  - The raw user requirement text (stored as `query.raw`)
  - Tool result summaries (returned by the executor)
  - Diagnostic messages emitted by validators

It is intentionally regex-based and conservative: false positives
(replacing a non-secret with [REDACTED]) are acceptable; false negatives
(leaking a real secret) are not.
"""

from __future__ import annotations

import re
from typing import Any


# Order matters: private keys must be matched before generic "key=..."
# patterns so we don't fragment them.
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # PEM private keys (RSA, EC, OPENSSH, generic)
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"
            r"[\s\S]*?"
            r"-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
            re.MULTILINE,
        ),
        "[REDACTED_KEY]",
    ),
    # Bearer tokens in Authorization headers or inline
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"), "[REDACTED_BEARER]"),
    # Generic API key patterns: apiKey=..., api_key=..., X-API-Key: ...
    (re.compile(r"(?i)api[_-]?key[\s:=]+[\"']?[A-Za-z0-9\-_]{16,}[\"']?"), "apiKey=[REDACTED]"),
    # Passwords (URL-encoded, JSON, YAML, query-string)
    (re.compile(r"(?i)password[\"'\s:=]+[\"'][^\"']+[\"']"), "password=[REDACTED]"),
    (re.compile(r"(?i)password=([^&\s\"']+)"), "password=[REDACTED]"),
    # Client secrets (OAuth2)
    (re.compile(r"(?i)client[_-]?secret[\"'\s:=]+[\"'][^\"']+[\"']"), "clientSecret=[REDACTED]"),
    # SAP-internal hostnames (anything *.sap.com)
    (re.compile(r"https?://[a-zA-Z0-9.\-]+\.sap\.com[^\s]*"), "[REDACTED_SAP_URL]"),
    # Generic UUID-like tokens that look like credentials (long hex >32 chars)
    (re.compile(r"\b[a-fA-F0-9]{40,}\b"), "[REDACTED_TOKEN]"),
    # Connection strings with embedded credentials
    (
        re.compile(r"(?i)(jdbc:[a-z]+://[^:]+:)[^@]+(@)"),
        r"\1[REDACTED]\2",
    ),
]


class Redactor:
    """Strip secrets, PII, and customer identifiers from text or dicts.

    Stateless: the same instance can be reused across trajectories.
    """

    # Keys whose VALUES should be redacted regardless of content.
    # Match is case-insensitive substring.
    SECRET_KEYS = (
        "password",
        "passwd",
        "secret",
        "clientsecret",
        "client_secret",
        "apikey",
        "api_key",
        "accesstoken",
        "access_token",
        "refreshtoken",
        "refresh_token",
        "bearer",
        "authorization",
        "credential",
        "privatekey",
        "private_key",
    )

    def __init__(self, extra_patterns: list[tuple[str, str]] | None = None):
        self.patterns = list(PATTERNS)
        if extra_patterns:
            for pat, repl in extra_patterns:
                self.patterns.append((re.compile(pat), repl))

    def redact(self, text: str) -> str:
        """Apply all redaction patterns to a string."""
        if not isinstance(text, str):
            return text
        for pattern, replacement in self.patterns:
            text = pattern.sub(replacement, text)
        return text

    def _is_secret_key(self, key: str) -> bool:
        if not isinstance(key, str):
            return False
        lowered = key.lower()
        return any(secret in lowered for secret in self.SECRET_KEYS)

    def redact_dict(self, d: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact string values in a dict.

        Two redaction paths:
          1. Pattern-based: regex over string values (catches inline
             `password=foo` even when the dict key is unrelated).
          2. Key-based: if the dict KEY suggests a secret (password,
             secret, token, ...), the value is replaced with
             '[REDACTED]' regardless of its content.

        Non-string values (ints, bools, lists) are passed through unless
        their key marks them as secret. Lists are descended into.
        """
        if not isinstance(d, dict):
            return d
        out: dict[str, Any] = {}
        for k, v in d.items():
            if self._is_secret_key(k) and v is not None:
                # Key-based redaction: replace any non-None value
                if isinstance(v, (dict, list)):
                    out[k] = "[REDACTED]"
                else:
                    out[k] = "[REDACTED]"
            elif isinstance(v, str):
                out[k] = self.redact(v)
            elif isinstance(v, dict):
                out[k] = self.redact_dict(v)
            elif isinstance(v, list):
                out[k] = [
                    self.redact_dict(x) if isinstance(x, dict)
                    else (self.redact(x) if isinstance(x, str) else x)
                    for x in v
                ]
            else:
                out[k] = v
        return out

    def redact_any(self, value: Any) -> Any:
        """Redact a value of unknown shape (str / dict / list / other)."""
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return self.redact_dict(value)
        if isinstance(value, list):
            return [self.redact_any(x) for x in value]
        return value


__all__ = ["Redactor", "PATTERNS"]
