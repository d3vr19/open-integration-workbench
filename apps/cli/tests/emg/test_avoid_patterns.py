"""Tests for AvoidPatternStore (WP-07 Track E-002 integration).

Verifies:
  - Loading patterns from YAML
  - find_for_action: matching by operation + componentType + config
  - find_for_requirement: matching by archetype + components
  - Wildcard component matching (receiver.*)
  - configMissing / configSet / configContains triggers
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.emg.avoid_patterns import (  # noqa: E402
    AvoidPatternStore,
    _component_matches,
    _has_config_path,
)


@pytest.fixture
def sample_yaml(tmp_path: Path) -> Path:
    """A sample negative-knowledge YAML for testing."""
    doc = {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "NegativeKnowledgeCatalog",
        "metadata": {"version": "0.1.0"},
        "spec": {
            "avoidPatterns": [
                {
                    "id": "avoid-fm-001",
                    "trigger": {
                        "operation": "add-node",
                        "componentType": "receiver.odata-v4",
                        "configMissing": "pagination.maxPages",
                    },
                    "reason": "Unbounded pagination",
                    "severity": "high",
                    "replacement": [{"op": "updateNodeConfig", "config": {}}],
                    "evidence": {"failureModeId": "fm-001", "archetype": "paginated-api-ingestion"},
                    "provenance": {"source": "failure-modes-catalog", "isReal": True},
                },
                {
                    "id": "avoid-fm-004",
                    "trigger": {
                        "operation": "add-node",
                        "componentType": "receiver.*",
                        "configContains": r"smtps://.*:.*@",
                    },
                    "reason": "Inline secret in URL",
                    "severity": "critical",
                    "replacement": [],
                    "evidence": {"failureModeId": "fm-004", "archetype": "any"},
                    "provenance": {"source": "failure-modes-catalog", "isReal": True},
                },
                {
                    "id": "avoid-fm-008",
                    "trigger": {
                        "operation": "add-node",
                        "componentType": "receiver.http",
                        "configMissing": "timeoutSeconds",
                    },
                    "reason": "Missing timeout",
                    "severity": "low",
                    "replacement": [],
                    "evidence": {"failureModeId": "fm-008", "archetype": "any"},
                    "provenance": {"source": "failure-modes-catalog", "isReal": True},
                },
            ]
        },
    }
    p = tmp_path / "neg.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


class TestAvoidPatternStore:
    def test_load_from_yaml(self, sample_yaml: Path) -> None:
        """3 patterns loaded from YAML."""
        store = AvoidPatternStore.from_yaml(sample_yaml)
        assert store.count() == 3

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Missing YAML → empty store (no crash)."""
        store = AvoidPatternStore.from_yaml(tmp_path / "nonexistent.yaml")
        assert store.count() == 0

    def test_list_all_sorted_by_severity(self, sample_yaml: Path) -> None:
        """Critical patterns come first."""
        store = AvoidPatternStore.from_yaml(sample_yaml)
        all_patterns = store.list_all()
        severities = [p.severity for p in all_patterns]
        assert severities[0] == "critical"  # fm-004
        assert severities[-1] == "low"  # fm-008

    def test_find_for_action_matching_component(self, sample_yaml: Path) -> None:
        """Add-node on receiver.odata-v4 triggers fm-001 (missing pagination)."""
        store = AvoidPatternStore.from_yaml(sample_yaml)
        matches = store.find_for_action(
            action_type="add-node",
            component_type="receiver.odata-v4",
            config={"serviceUrl": "https://api.example.com"},  # no pagination
        )
        ids = [p.id for p in matches]
        assert "avoid-fm-001" in ids  # configMissing pagination.maxPages

    def test_find_for_action_with_config_present_no_match(self, sample_yaml: Path) -> None:
        """If config HAS the required key, the avoid pattern doesn't apply."""
        store = AvoidPatternStore.from_yaml(sample_yaml)
        matches = store.find_for_action(
            action_type="add-node",
            component_type="receiver.odata-v4",
            config={"pagination": {"maxPages": 100}},  # has pagination
        )
        ids = [p.id for p in matches]
        assert "avoid-fm-001" not in ids

    def test_find_for_action_wildcard_component(self, sample_yaml: Path) -> None:
        """receiver.* matches receiver.mail with inline secret."""
        store = AvoidPatternStore.from_yaml(sample_yaml)
        matches = store.find_for_action(
            action_type="add-node",
            component_type="receiver.mail",
            config={"smtpUrl": "smtps://user:pass@example.com:465"},
        )
        ids = [p.id for p in matches]
        assert "avoid-fm-004" in ids  # configContains smtps://user:pass@

    def test_find_for_action_no_config_no_configmissing_match(self, sample_yaml: Path) -> None:
        """If trigger has configMissing but no config provided, skip that check."""
        store = AvoidPatternStore.from_yaml(sample_yaml)
        # No config provided — configMissing check is skipped
        matches = store.find_for_action(
            action_type="add-node",
            component_type="receiver.http",
            config=None,
        )
        ids = [p.id for p in matches]
        # fm-008 should match (operation=add-node, componentType=receiver.http)
        # because we can't verify the config
        assert "avoid-fm-008" in ids

    def test_find_for_requirement_by_archetype(self, sample_yaml: Path) -> None:
        """Paginated-api-ingestion archetype returns fm-001 + fm-004 + fm-008 (any)."""
        store = AvoidPatternStore.from_yaml(sample_yaml)
        matches = store.find_for_requirement(
            archetype="paginated-api-ingestion",
            components=["receiver.odata-v4"],
        )
        ids = {p.id for p in matches}
        # fm-001 (paginated), fm-004 (any), fm-008 (any)
        assert "avoid-fm-001" in ids
        assert "avoid-fm-004" in ids
        assert "avoid-fm-008" in ids

    def test_find_for_requirement_archetype_filter(self, sample_yaml: Path) -> None:
        """A non-matching archetype filters out non-'any' patterns."""
        store = AvoidPatternStore.from_yaml(sample_yaml)
        matches = store.find_for_requirement(
            archetype="soap-integration",  # doesn't match fm-001's paginated-api-ingestion
            components=["receiver.soap"],
        )
        ids = {p.id for p in matches}
        # fm-001 has archetype=paginated-api-ingestion → excluded
        assert "avoid-fm-001" not in ids
        # fm-004 and fm-008 have archetype=any → included
        assert "avoid-fm-004" in ids
        assert "avoid-fm-008" in ids


class TestComponentMatchHelpers:
    def test_exact_match(self) -> None:
        assert _component_matches("receiver.http", "receiver.http")

    def test_wildcard_match(self) -> None:
        assert _component_matches("receiver.*", "receiver.http")
        assert _component_matches("receiver.*", "receiver.odata-v4")
        assert _component_matches("receiver.*", "receiver.mail")

    def test_no_match(self) -> None:
        assert not _component_matches("receiver.http", "sender.http")
        assert not _component_matches("receiver.http", "receiver.odata-v4")


class TestConfigPathHelper:
    def test_top_level_key(self) -> None:
        assert _has_config_path({"timeoutSeconds": 30}, "timeoutSeconds")

    def test_nested_key_present(self) -> None:
        config = {"pagination": {"maxPages": 100, "pageSize": 50}}
        assert _has_config_path(config, "pagination.maxPages")
        assert _has_config_path(config, "pagination.pageSize")

    def test_nested_key_missing(self) -> None:
        config = {"pagination": {"maxPages": 100}}
        assert not _has_config_path(config, "pagination.pageSize")

    def test_missing_top_level(self) -> None:
        assert not _has_config_path({}, "timeoutSeconds")

    def test_non_dict_intermediate(self) -> None:
        assert not _has_config_path({"pagination": "not-a-dict"}, "pagination.maxPages")
