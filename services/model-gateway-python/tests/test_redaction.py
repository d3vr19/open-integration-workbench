"""Tests for the redaction layer.

Spec ref: §12.7 (redaction), §4.6 (secrets never enter LLM context).
"""

from __future__ import annotations

from oiw_gateway.redaction import redact, redact_messages

# ---------------------------------------------------------------------
# Secret pattern redaction
# ---------------------------------------------------------------------


def test_redact_bearer_token() -> None:
    text = "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature"
    result = redact(text)
    assert "<redacted-bearer-token>" in result.redacted_text
    assert "eyJhbGciOiJSUzI1NiJ9" not in result.redacted_text
    assert result.redaction_count > 0


def test_redact_api_key() -> None:
    text = "api_key=sk-abc123def456ghi789jkl012mno345pqr678"
    result = redact(text)
    assert "<redacted-api-key>" in result.redacted_text
    assert "sk-abc123def456ghi789jkl012mno345pqr678" not in result.redacted_text


def test_redact_password() -> None:
    text = 'password = "supersecret123value"'
    result = redact(text)
    assert "<redacted>" in result.redacted_text
    assert "supersecret123value" not in result.redacted_text


def test_redact_secret() -> None:
    text = 'secret: "my-super-secret-value"'
    result = redact(text)
    assert "<redacted>" in result.redacted_text
    assert "my-super-secret-value" not in result.redacted_text


def test_redact_token() -> None:
    text = 'token: "abc123def456ghi789"'
    result = redact(text)
    assert "<redacted>" in result.redacted_text


def test_redact_private_key() -> None:
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    result = redact(text)
    assert "<redacted-private-key>" in result.redacted_text
    assert "MIIEpAIBAAKCAQEA" not in result.redacted_text


def test_redact_basic_auth() -> None:
    text = "Authorization: Basic dXNlcjpwYXNzd29yZA=="
    result = redact(text)
    assert "<redacted>" in result.redacted_text
    assert "dXNlcjpwYXNzd29yZA==" not in result.redacted_text


def test_redact_long_credential_ref() -> None:
    """A credentialRef that looks like an actual secret (50+ chars) should be redacted."""
    long_secret = "A" * 60
    text = f'credentialRef: "{long_secret}"'
    result = redact(text)
    assert "<redacted-looks-like-secret>" in result.redacted_text
    assert long_secret not in result.redacted_text


def test_redact_short_credential_ref_preserved() -> None:
    """A short credentialRef identifier should be preserved (it's not a secret)."""
    text = 'credentialRef: "s4-api-client"'
    result = redact(text)
    assert "s4-api-client" in result.redacted_text
    assert "<redacted" not in result.redacted_text


def test_redact_tenant_url() -> None:
    text = "Deploy to https://mytenant.integration.sap-cloud.cn/api/v1"
    result = redact(text)
    assert "<tenant-url>" in result.redacted_text or "<sap-host-url>" in result.redacted_text
    assert "mytenant.integration.sap-cloud.cn" not in result.redacted_text


def test_redact_no_secrets() -> None:
    """Text without secrets should pass through unchanged."""
    text = "This is a normal integration flow with no secrets."
    result = redact(text)
    assert result.redacted_text == text
    assert result.redaction_count == 0


def test_redact_empty_string() -> None:
    result = redact("")
    assert result.redacted_text == ""
    assert result.redaction_count == 0


# ---------------------------------------------------------------------
# Message redaction
# ---------------------------------------------------------------------


def test_redact_messages_string_content() -> None:
    messages = [
        {"role": "user", "content": "My api_key=sk-abc123def456ghi789jkl012mno345pqr678"},
    ]
    redacted, redactions = redact_messages(messages)
    assert "sk-abc123def456" not in redacted[0]["content"]
    assert "<redacted-api-key>" in redacted[0]["content"]
    assert len(redactions) > 0


def test_redact_messages_multipart_content() -> None:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Password: supersecret123value"},
                {"type": "text", "text": "Normal text"},
            ],
        },
    ]
    redacted, redactions = redact_messages(messages)
    assert "supersecret123value" not in redacted[0]["content"][0]["text"]
    assert "Normal text" in redacted[0]["content"][1]["text"]
    assert len(redactions) > 0


def test_redact_messages_preserves_structure() -> None:
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
    ]
    redacted, _ = redact_messages(messages)
    assert len(redacted) == 2
    assert redacted[0]["role"] == "system"
    assert redacted[1]["role"] == "user"
