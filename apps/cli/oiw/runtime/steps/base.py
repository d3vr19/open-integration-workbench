"""Step plugin SPI.

Spec ref: §9.3 (Step Plugin SPI).
"""

from __future__ import annotations

import abc
from typing import Any

from ...project import FlowNode
from ..context import MessageContext


class StepPlugin(abc.ABC):
    """Step plugin interface (spec §9.3).

    Each plugin provides:
      - type identifier
      - JSON Schema for configuration (config_schema)
      - UI form metadata (ui_schema)
      - validation rules (validate)
      - local runtime implementation (compile / execute)
      - compatibility descriptor (compatibility)
      - security classification (security_classification)
    """

    @abc.abstractmethod
    def descriptor(self) -> dict[str, Any]:
        """Return {'type': ..., 'name': ..., 'description': ...}."""

    @abc.abstractmethod
    def config_schema(self) -> dict[str, Any]:
        """JSON Schema for this step's `config` block."""

    def ui_schema(self) -> dict[str, Any]:
        """UI form metadata (Phase 2 visual designer uses this)."""
        return {}

    def validate(self, node: FlowNode) -> list[str]:
        """Return a list of validation errors (empty list = OK)."""
        return []

    @abc.abstractmethod
    def execute(
        self, node: FlowNode, ctx: MessageContext, mocks: dict[str, dict[str, Any]]
    ) -> MessageContext:
        """Execute the step against the message context."""

    def compatibility(self) -> dict[str, Any]:
        return {"fidelity": "simulated", "target_profiles": []}

    def security_classification(self) -> str:
        """SANDBOXED | TRUSTED | NETWORK per spec §9.3."""
        return "SANDBOXED"


_REGISTRY: dict[str, StepPlugin] = {}


def register(plugin: StepPlugin) -> None:
    desc = plugin.descriptor()
    plugin_type = desc["type"]
    if plugin_type in _REGISTRY:
        raise RuntimeError(f"duplicate step plugin for type {plugin_type!r}")
    _REGISTRY[plugin_type] = plugin


def get_plugin(node_type: str) -> StepPlugin | None:
    return _REGISTRY.get(node_type)


def all_plugins() -> dict[str, StepPlugin]:
    return dict(_REGISTRY)
