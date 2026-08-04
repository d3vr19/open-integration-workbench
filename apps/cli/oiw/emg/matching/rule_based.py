"""Rule-based matcher — Stage 2 (WP-05 Task 10).

Spec ref: §15.7 (Matching Stages), Stage 2: rule-based match.

Applies equivalence rules to unmatched nodes from Stage 1:
  1. Aliases — component type aliases (e.g., receiver-http ≡ outbound-http-adapter)
  2. Diagnostic class grouping — related diagnostic codes map to the same class
  3. Role mapping — node ID patterns map to roles (e.g., node-abc123 → anonymous-node)

This stage is more permissive than ExactMatcher — it catches semantically
equivalent actions that use different naming conventions.
"""

from __future__ import annotations

import re

from ..graph_builder import ActionDecisionGraph
from .common import MatchResult

# Component type aliases (spec §15.7 Stage 2).
# Keys are exploration-side names; values are the canonical expert-side name.
ALIASES: dict[str, str] = {
    "receiver-http": "outbound-http-adapter",
    "outbound-http-adapter": "receiver-http",
    "sender-https": "inbound-https-sender",
    "inbound-https-sender": "sender-https",
    "script-groovy": "groovy-script-step",
    "groovy-script-step": "script-groovy",
    "validator-json-schema": "json-schema-validator",
    "json-schema-validator": "validator-json-schema",
}

# Diagnostic code → diagnostic class grouping.
# Codes in the same class are considered equivalent for matching.
DIAGNOSTIC_CLASSES: dict[str, str] = {
    "OIW-E001": "missing-endpoint",
    "OIW-E007": "missing-endpoint",
    "OIW-E002": "inline-secret",
    "OIW-E008": "inline-secret",
    "OIW-E003": "unbounded-splitter",
    "OIW-E009": "unbounded-splitter",
}

# Node ID → role mapping (regex patterns).
# Applied to the action's normalized tuple to extract a role.
ROLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"node-[a-f0-9]+"), "anonymous-node"),
    (re.compile(r"sender-[a-z]+"), "sender"),
    (re.compile(r"receiver-[a-z]+"), "receiver"),
    (re.compile(r"validator-[a-z]+"), "validator"),
    (re.compile(r"script-[a-z]+"), "script"),
]


class RuleBasedMatcher:
    """Stage 2: aliases, diagnostic class grouping, role mapping."""

    def __init__(
        self,
        aliases: dict[str, str] | None = None,
        diagnostic_classes: dict[str, str] | None = None,
        role_patterns: list[tuple[re.Pattern[str], str]] | None = None,
    ):
        self.aliases = aliases or ALIASES
        self.diagnostic_classes = diagnostic_classes or DIAGNOSTIC_CLASSES
        self.role_patterns = role_patterns or ROLE_PATTERNS

    def match(
        self,
        exploration: ActionDecisionGraph,
        expert: ActionDecisionGraph,
        prior: MatchResult,
    ) -> MatchResult:
        """Apply rule-based equivalences to unmatched nodes from Stage 1.

        Args:
            exploration: the exploration ADG.
            expert: the expert ADG.
            prior: the MatchResult from ExactMatcher (Stage 1).

        Returns:
            New MatchResult with stage="rule-based", combining exact + rule matches.
        """
        correspondence = dict(prior.correspondence)

        for exp_node in list(prior.unmatched_explored):
            exp_data = exploration.graph.nodes[exp_node]
            for expert_node in list(prior.unmatched_expert):
                if expert_node in correspondence.values():
                    continue  # Already matched
                expert_data = expert.graph.nodes[expert_node]
                if self._rule_equivalent(exp_data, expert_data):
                    correspondence[exp_node] = expert_node
                    break

        all_explored = {n for n in exploration.graph.nodes if n != "INIT"}
        all_expert = {n for n in expert.graph.nodes if n != "INIT"}
        confidence = len(correspondence) / max(len(all_explored), 1) if all_explored else 0.0

        return MatchResult(
            stage="rule-based",
            correspondence=correspondence,
            confidence=confidence,
            unmatched_explored=all_explored - set(correspondence.keys()),
            unmatched_expert=all_expert - set(correspondence.values()),
        )

    def _rule_equivalent(self, a: dict, b: dict) -> bool:
        """Check if two unmatched nodes are equivalent under the rules."""
        a_action = a.get("action")
        b_action = b.get("action")
        if a_action is None or b_action is None:
            return False

        a_norm = tuple(str(x) for x in a_action.normalized)
        b_norm = tuple(str(x) for x in b_action.normalized)

        # Rule 1: alias match on componentType (index 2 of normalized tuple)
        if len(a_norm) >= 3 and len(b_norm) >= 3:
            a_comp = a_norm[2]
            b_comp = b_norm[2]
            if a_comp == b_comp:
                return True
            if self.aliases.get(a_comp) == b_comp or self.aliases.get(b_comp) == a_comp:
                return True

        # Rule 2: diagnostic class match
        a_diag = a.get("diagnostic_code")
        b_diag = b.get("diagnostic_code")
        if a_diag and b_diag:
            a_class = self.diagnostic_classes.get(a_diag)
            b_class = self.diagnostic_classes.get(b_diag)
            if a_class and b_class and a_class == b_class:
                return True

        # Rule 3: role mapping — both nodes map to the same role
        a_role = self._extract_role(a_norm)
        b_role = self._extract_role(b_norm)
        return bool(a_role and b_role and a_role == b_role)

    def _extract_role(self, normalized: tuple[str, ...]) -> str | None:
        """Extract a role from the normalized action tuple.

        Checks the componentType (index 2) and semanticTarget (index 3)
        against the role patterns.
        """
        for idx in (2, 3):  # componentType, semanticTarget
            if idx < len(normalized):
                value = normalized[idx]
                for pattern, role in self.role_patterns:
                    if pattern.search(value):
                        return role
        return None


__all__ = ["RuleBasedMatcher", "ALIASES", "DIAGNOSTIC_CLASSES", "ROLE_PATTERNS"]
