"""P5b world dynamics — fault-injection scenarios for the simulated world.

The environment the organism lives in: declarative receiver behaviors that
compile into the runtime's `mocks` seam, producing REALISTIC failures
(timeouts, 5xx, malformed payloads, schema drift, connection resets) that
exercise error propagation and feed learning.

Scenario DSL (YAML):

    name: open-meteo-flaky
    receivers:
      fetch-weather:
        status: 200
        body: '{"temperature": 16.4}'
        faults:
          - kind: timeout          # raises like a hung endpoint
          - kind: http_status      # canned 5xx
            status: 503
          - kind: malformed        # truncated JSON body (downstream parse fails)
          - kind: drift            # remove fields from a valid JSON body
            remove: ["current"]
          - kind: connection_reset # transport-level failure

`build_world_mocks()` compiles a scenario into the per-node mock dicts the
engine plugins already consume; fault kinds requiring runtime behavior are
honored by the step plugin via the `fail` key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

FAULT_KINDS = ("http_status", "timeout", "malformed", "drift", "connection_reset")


@dataclass
class Fault:
    """One injected failure at a receiver."""

    kind: str
    status: int = 500  # http_status kind: the canned response code
    body: str = ""  # http_status kind: optional response body
    remove: list[str] = field(default_factory=list)  # drift kind: JSON keys to drop


@dataclass
class ReceiverWorld:
    """Behavior of one receiver node in this world scenario."""

    node_id: str
    status: int = 200
    body: str | None = None  # None → plugin default (empty 200 OK)
    headers: dict[str, str] = field(default_factory=dict)
    faults: list[Fault] = field(default_factory=list)


@dataclass
class WorldScenario:
    """A full environment: named behaviors per receiver node."""

    name: str
    receivers: list[ReceiverWorld] = field(default_factory=list)

    def for_node(self, node_id: str) -> ReceiverWorld | None:
        return next((r for r in self.receivers if r.node_id == node_id), None)


def scenario_from_dict(data: dict) -> WorldScenario:
    receivers = []
    for node_id, spec in (data.get("receivers") or {}).items():
        faults = [
            Fault(**{k: v for k, v in f.items() if k != "kind"}, kind=f["kind"])
            for f in spec.get("faults", [])
        ]
        receivers.append(
            ReceiverWorld(
                node_id=node_id,
                status=int(spec.get("status", 200)),
                body=spec.get("body"),
                headers=dict(spec.get("headers") or {}),
                faults=faults,
            )
        )
    return WorldScenario(name=str(data.get("name", "world")), receivers=receivers)


def scenario_from_yaml(path: Path | str) -> WorldScenario:
    return scenario_from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def build_world_mocks(scenario: WorldScenario) -> dict[str, dict]:
    """Compile the scenario into engine `mocks` dicts keyed by node id.

    The LAST fault wins as the terminal behavior (scenarios compose
    happy-path first, faults after); kinds that need runtime participation
    (timeout / connection_reset / body mutation) travel via the `fail`
    key and are honored by the step plugin.
    """
    mocks: dict[str, dict] = {}
    for r in scenario.receivers:
        mock: dict = {"respond": {"status": r.status}}
        if r.body is not None:
            mock["respond"]["body"] = r.body
        if r.headers:
            mock["respond"]["headers"] = dict(r.headers)
        for f in r.faults:
            if f.kind == "http_status":
                mock["respond"] = {"status": f.status, "body": f.body}
            elif f.kind == "timeout":
                mock["fail"] = {"kind": "timeout"}
            elif f.kind == "connection_reset":
                mock["fail"] = {"kind": "connection_reset"}
            elif f.kind == "malformed":
                base = _base_json(r.body)
                mock["respond"]["body"] = base[: max(1, len(base) // 2)]  # truncate mid-token
                mock["fail"] = {"kind": "malformed"}  # marker: downstream parse must fail
            elif f.kind == "drift":
                base = _base_json(r.body)
                doc = yaml.safe_load(base) if base else {}
                if isinstance(doc, dict):
                    for key in f.remove:
                        doc.pop(key, None)
                mock["respond"]["body"] = (
                    yaml.safe_dump(doc, default_flow_style=False).rstrip("\n")
                    if isinstance(doc, dict | list)
                    else base
                )
                mock["fail"] = {"kind": "drift", "remove": list(f.remove)}
            else:
                raise ValueError(f"unknown fault kind {f.kind!r} (expected one of {FAULT_KINDS})")
        mocks[r.node_id] = mock
    return mocks


def _base_json(body: str | None) -> str:
    """Seed body for mutation-based faults when none was configured."""
    return body or '{"latitude": 52.52, "longitude": 13.41, "current": {"temperature_2m": 16.4}}'
