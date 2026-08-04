"""Tests for failure mode catalog (WP-07 Task B-002)."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestFailureModeCatalog:
    def test_catalog_has_10_plus_failure_modes(self) -> None:
        """≥ 10 failure modes catalogued."""
        catalog_path = REPO_ROOT / "packages" / "seed-corpus" / "failure-modes.yaml"
        catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
        modes = catalog["spec"]["failureModes"]
        assert len(modes) >= 10

    def test_each_mode_has_diagnostic_and_correction(self) -> None:
        """Each failure mode has a diagnostic code and correction action."""
        catalog_path = REPO_ROOT / "packages" / "seed-corpus" / "failure-modes.yaml"
        catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
        for mode in catalog["spec"]["failureModes"]:
            assert mode["diagnostic"], f"missing diagnostic for {mode['id']}"
            assert mode["correction"], f"missing correction for {mode['id']}"
            assert mode["name"], f"missing name for {mode['id']}"
            assert mode["severity"] in ("low", "medium", "high", "critical")

    def test_catalog_covers_4_plus_archetypes(self) -> None:
        """Catalog covers at least 4 different archetypes."""
        catalog_path = REPO_ROOT / "packages" / "seed-corpus" / "failure-modes.yaml"
        catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
        archetypes = {m["archetype"] for m in catalog["spec"]["failureModes"]}
        # "any" counts as universal; need 4+ distinct archetypes including "any"
        assert len(archetypes) >= 4

    def test_catalog_includes_critical_severity(self) -> None:
        """Catalog includes at least one critical severity failure mode."""
        catalog_path = REPO_ROOT / "packages" / "seed-corpus" / "failure-modes.yaml"
        catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
        critical = [
            m for m in catalog["spec"]["failureModes"] if m["severity"] == "critical"
        ]
        assert len(critical) >= 1
