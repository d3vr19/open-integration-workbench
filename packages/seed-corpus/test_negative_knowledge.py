"""Tests for negative knowledge population (WP-07 Track E-002)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from negative_knowledge import (
    build_avoid_patterns,
    populate_negative_knowledge,
    write_avoid_patterns_yaml,
)


class TestAvoidPatterns:
    def test_builds_12_patterns(self) -> None:
        """One AvoidPattern per failure mode (fm-001 through fm-012)."""
        patterns = build_avoid_patterns()
        assert len(patterns) == 12

    def test_each_pattern_has_required_fields(self) -> None:
        """Every AvoidPattern has trigger, reason, severity, replacement."""
        patterns = build_avoid_patterns()
        for p in patterns:
            assert p.id.startswith("avoid-fm-")
            assert p.trigger  # non-empty
            assert p.reason
            assert p.severity in ("critical", "high", "medium", "low")
            assert len(p.replacement) >= 1
            assert p.evidence["failureModeId"]
            assert p.evidence["diagnostic"]
            assert p.provenance["source"] == "failure-modes-catalog"
            assert p.provenance["reviewer"]
            assert p.provenance["isReal"] is True

    def test_critical_severity_patterns_exist(self) -> None:
        """Critical-severity patterns are present (fm-004 secret, fm-007 sandbox)."""
        patterns = build_avoid_patterns()
        severities = {p.id: p.severity for p in patterns}
        # fm-004 = inline secret, fm-007 = sandbox violation → both critical
        assert severities["avoid-fm-004"] == "critical"
        assert severities["avoid-fm-007"] == "critical"

    def test_replacement_uses_typed_actions(self) -> None:
        """Replacements use typed op format (op + config/path/nodeId)."""
        patterns = build_avoid_patterns()
        valid_ops = {
            "addNode",
            "removeNode",
            "updateNodeConfig",
            "addEdge",
            "removeEdge",
            "resource.write",
            "setConfig",
        }
        for p in patterns:
            for r in p.replacement:
                assert "op" in r, f"{p.id}: replacement missing 'op': {r}"
                assert r["op"] in valid_ops, f"{p.id}: unknown op {r['op']}"

    def test_write_yaml_round_trip(self, tmp_path: Path) -> None:
        """Patterns can be written to YAML and re-read."""
        patterns = build_avoid_patterns()
        out = write_avoid_patterns_yaml(patterns, tmp_path / "neg.yaml")
        assert out.is_file()

        doc = yaml.safe_load(out.read_text())
        assert doc["kind"] == "NegativeKnowledgeCatalog"
        assert len(doc["spec"]["avoidPatterns"]) == 12

    def test_populate_negative_knowledge(self, tmp_path: Path) -> None:
        """populate_negative_knowledge writes ≥10 patterns."""
        summary = populate_negative_knowledge(tmp_path / "neg.yaml")
        assert summary["totalPatterns"] >= 10
        assert (tmp_path / "neg.yaml").is_file()

    def test_trigger_conditions_diverse(self) -> None:
        """Triggers cover different trigger types (configMissing, configSet, etc.)."""
        patterns = build_avoid_patterns()
        trigger_keys: set[str] = set()
        for p in patterns:
            trigger_keys.update(p.trigger.keys())
        # Should see at least: operation, componentType, configMissing
        assert "operation" in trigger_keys
        assert "componentType" in trigger_keys
        assert "configMissing" in trigger_keys or "configSet" in trigger_keys
