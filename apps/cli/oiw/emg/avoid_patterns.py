"""Avoid-pattern store (WP-07 Track E-002 enhancement).

Spec ref: §15.11 (Avoid Patterns).

Loads AvoidPattern entries from negative-knowledge.yaml and provides:

  1. `find_for_action(action_type, component_type, config)` — returns
     patterns whose trigger matches a planned action.
  2. `find_for_requirement(normalized_requirement)` — returns patterns
     whose archetype / component family matches a requirement.

The store is consumed by EMGRetriever.retrieve() so the orchestrator
gets avoid patterns alongside positive insights. The orchestrator
includes them in the plan rationale ("avoid: fm-004 inline secret
in receiver config — use credentialRef instead").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AvoidPattern:
    """A 'don't do this' pattern (mirrors negative-knowledge.yaml schema)."""

    id: str
    trigger: dict[str, Any]
    reason: str
    severity: str  # critical | high | medium | low
    replacement: list[dict[str, Any]]
    evidence: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AvoidPattern:
        return cls(
            id=d["id"],
            trigger=d.get("trigger", {}),
            reason=d.get("reason", ""),
            severity=d.get("severity", "medium"),
            replacement=d.get("replacement", []),
            evidence=d.get("evidence", {}),
            provenance=d.get("provenance", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trigger": self.trigger,
            "reason": self.reason,
            "severity": self.severity,
            "replacement": self.replacement,
            "evidence": self.evidence,
            "provenance": self.provenance,
        }


class AvoidPatternStore:
    """In-memory store of avoid patterns.

    Patterns are loaded from a YAML catalog (default:
    packages/seed-corpus/negative-knowledge.yaml) and indexed by
    componentType for fast lookup during planning.
    """

    def __init__(self, patterns: list[AvoidPattern] | None = None):
        self._patterns: list[AvoidPattern] = patterns or []
        self._by_component: dict[str, list[AvoidPattern]] = {}
        self._rebuild_index()

    @classmethod
    def from_yaml(cls, path: Path | str) -> AvoidPatternStore:
        """Load avoid patterns from a YAML catalog file."""
        path = Path(path)
        if not path.is_file():
            return cls(patterns=[])
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        patterns = [AvoidPattern.from_dict(p) for p in doc.get("spec", {}).get("avoidPatterns", [])]
        return cls(patterns=patterns)

    def add(self, pattern: AvoidPattern) -> None:
        """Add a single pattern and re-index."""
        self._patterns.append(pattern)
        self._index_pattern(pattern)

    def list_all(self) -> list[AvoidPattern]:
        """Return all patterns (sorted by severity, critical first)."""
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(self._patterns, key=lambda p: severity_order.get(p.severity, 99))

    def count(self) -> int:
        return len(self._patterns)

    def find_for_action(
        self,
        action_type: str,
        component_type: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> list[AvoidPattern]:
        """Find patterns whose trigger matches a planned action.

        Args:
            action_type: e.g. "addNode", "updateNodeConfig"
            component_type: e.g. "receiver.odata-v4"
            config: the config dict being applied (for configMissing checks)

        Returns:
            List of matching AvoidPattern objects.
        """
        matches: list[AvoidPattern] = []
        for p in self._patterns:
            trig = p.trigger
            if trig.get("operation") and trig["operation"] != action_type:
                continue

            # Component type matching — supports wildcards like "receiver.*"
            trig_comp = trig.get("componentType", "")
            if trig_comp and component_type:
                if not _component_matches(trig_comp, component_type):
                    continue
            elif trig_comp and not component_type:
                # Trigger wants a specific component but none provided
                continue

            # configMissing check — flag if the trigger says a config key
            # MUST be present and it's not in the planned config
            missing_key = trig.get("configMissing")
            if missing_key and config is not None and _has_config_path(config, missing_key):
                # The config DOES have this key, so the avoid pattern
                # does NOT apply
                continue

            # configSet check — flag if the trigger says a config key IS
            # being set that should be avoided
            set_key = trig.get("configSet")
            if set_key and config is not None and not _has_config_path(config, set_key):
                continue

            # configContains check — regex match against a config value
            contains_pattern = trig.get("configContains")
            if contains_pattern and config is not None:
                import re

                pattern = re.compile(contains_pattern)
                if not any(isinstance(v, str) and pattern.search(v) for v in _flatten_config_values(config)):
                    continue

            matches.append(p)

        return matches

    def find_for_requirement(
        self,
        archetype: str | None = None,
        components: list[str] | None = None,
    ) -> list[AvoidPattern]:
        """Find patterns whose archetype / component family matches a requirement.

        This is used by the EMGRetriever to surface avoid patterns even
        before the agent commits to specific actions.
        """
        matches: list[AvoidPattern] = []
        for p in self._patterns:
            # Check archetype match — pattern evidence has 'archetype'
            # which may be 'any' (matches all)
            pattern_archetype = p.evidence.get("archetype", "any")
            if pattern_archetype != "any" and archetype and pattern_archetype != archetype:
                continue

            # Check component family match — if the pattern targets a
            # component family (e.g. "receiver.odata-v4") and the
            # requirement mentions that family
            trig_comp = p.trigger.get("componentType", "")
            if trig_comp and components:
                # Use loose matching: "receiver.odata-v4" matches if any
                # requirement component contains "odata" or "receiver"
                trig_lower = trig_comp.lower()
                keywords = [k for k in trig_lower.replace("*", "").split(".") if k]
                if not any(any(kw in c.lower() for kw in keywords) for c in components):
                    continue

            matches.append(p)

        return matches

    def _rebuild_index(self) -> None:
        """Rebuild the component-type index."""
        self._by_component = {}
        for p in self._patterns:
            self._index_pattern(p)

    def _index_pattern(self, pattern: AvoidPattern) -> None:
        comp = pattern.trigger.get("componentType", "")
        if comp:
            self._by_component.setdefault(comp, []).append(pattern)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _component_matches(pattern: str, actual: str) -> bool:
    """Check whether `actual` matches `pattern`.

    Supports wildcards: "receiver.*" matches "receiver.http",
    "receiver.odata-v4", etc.
    """
    if pattern == actual:
        return True
    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        return actual.startswith(prefix + ".") or actual == prefix
    return False


def _has_config_path(config: dict[str, Any], dotted_path: str) -> bool:
    """Check whether a dotted path exists in a nested config dict.

    Example: _has_config_path({"pagination": {"maxPages": 100}}, "pagination.maxPages") → True
    """
    parts = dotted_path.split(".")
    current: Any = config
    for part in parts:
        if not isinstance(current, dict):
            return False
        if part not in current:
            return False
        current = current[part]
    return True


def _flatten_config_values(config: Any) -> list[str]:
    """Flatten a nested config dict into a list of string values."""
    values: list[str] = []
    if isinstance(config, dict):
        for v in config.values():
            values.extend(_flatten_config_values(v))
    elif isinstance(config, list):
        for v in config:
            values.extend(_flatten_config_values(v))
    elif isinstance(config, str):
        values.append(config)
    return values


__all__ = ["AvoidPattern", "AvoidPatternStore"]
