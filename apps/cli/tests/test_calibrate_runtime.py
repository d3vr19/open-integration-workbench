"""Runtime-host derivation + entrypoint verb selection (oracle loop).

Live finding (2026-08-26): CPI message ingress (/http/<path>) lives on the
RUNTIME host whose landscape segment carries an '-rt' suffix. Sending to
the designtime host returns 403.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.tenant.calibrate import message_method, runtime_base_url  # noqa: E402

DESIGNTIME = "https://integration-suite-test-874gff1p.it-cpi021.cfapps.in30.hana.ondemand.com"


def test_runtime_host_inserts_rt_suffix(monkeypatch):
    monkeypatch.delenv("OIW_TENANT_RUNTIME_URL", raising=False)
    assert (
        runtime_base_url(DESIGNTIME)
        == "https://integration-suite-test-874gff1p.it-cpi021-rt.cfapps.in30.hana.ondemand.com"
    )


def test_runtime_host_strips_api_v1(monkeypatch):
    monkeypatch.delenv("OIW_TENANT_RUNTIME_URL", raising=False)
    assert (
        runtime_base_url(DESIGNTIME + "/api/v1")
        == "https://integration-suite-test-874gff1p.it-cpi021-rt.cfapps.in30.hana.ondemand.com"
    )


def test_runtime_host_idempotent_when_already_rt(monkeypatch):
    monkeypatch.delenv("OIW_TENANT_RUNTIME_URL", raising=False)
    rt = runtime_base_url(DESIGNTIME)
    assert runtime_base_url(rt) == rt


def test_runtime_host_env_override_wins(monkeypatch):
    monkeypatch.setenv("OIW_TENANT_RUNTIME_URL", "https://custom.example.com/")
    assert runtime_base_url(DESIGNTIME) == "https://custom.example.com"


def test_runtime_host_non_cf_unchanged(monkeypatch):
    monkeypatch.delenv("OIW_TENANT_RUNTIME_URL", raising=False)
    assert runtime_base_url("https://cpi.example.com/api/v1") == "https://cpi.example.com"


def test_message_method_prefers_declared_get():
    assert message_method({"config": {"path": "/x", "methods": ["GET"]}}) == "GET"
    assert message_method({"config": {"path": "/x", "methods": ["POST"]}}) == "POST"
    assert message_method({"config": {"methods": ["POST", "GET"]}}) == "GET"
    assert message_method({}) == "POST"


def test_message_content_type_inference() -> None:
    """XML probe bodies get XML content-type (prolog law, 2026-09-04)."""
    from oiw.tenant.calibrate import message_content_type

    assert message_content_type("<Order><id>1</id></Order>") == "application/xml"
    assert message_content_type('  \n<root/>') == "application/xml"
    assert message_content_type('{"a": 1}') == "application/json"
    assert message_content_type("{}") == "application/json"
    assert message_content_type("") == "application/json"
