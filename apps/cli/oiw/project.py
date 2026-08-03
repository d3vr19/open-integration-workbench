"""Project loader and IR model.

Spec ref: §7 (Canonical IR), §11.1 (repository structure).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ProjectError(Exception):
    """Raised when a project cannot be loaded or parsed."""


@dataclass
class FlowNode:
    id: str
    type: str
    config: dict[str, Any]
    fidelity: str = "simulated"


@dataclass
class FlowEdge:
    from_: str
    to: str
    condition: str | None = None


@dataclass
class Entrypoint:
    id: str
    type: str
    config: dict[str, Any]
    fidelity: str = "simulated"


@dataclass
class ErrorSubprocess:
    steps: list[FlowNode] = field(default_factory=list)


@dataclass
class IntegrationFlow:
    id: str
    name: str
    version: int
    entrypoints: list[Entrypoint]
    nodes: list[FlowNode]
    edges: list[FlowEdge]
    error_handling: ErrorSubprocess | None = None
    extensions: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    generated_by: dict[str, Any] | None = None
    source_path: Path | None = None
    diagram: dict[str, Any] | None = None


@dataclass
class FlowTest:
    name: str
    flow: str
    input: dict[str, Any]
    assertions: list[dict[str, Any]]
    mocks: list[dict[str, Any]] = field(default_factory=list)
    description: str = ""
    source_path: Path | None = None


@dataclass
class EnvironmentProfile:
    name: str
    target: str
    auth: dict[str, Any]
    deployment_policy: dict[str, Any]
    tenant_url: str | None = None
    externalized_parameters: dict[str, str] = field(default_factory=dict)
    source_path: Path | None = None


@dataclass
class Project:
    id: str
    name: str
    created: str
    spec: dict[str, Any]
    root: Path
    flows: list[IntegrationFlow] = field(default_factory=list)
    tests: list[FlowTest] = field(default_factory=list)
    environments: list[EnvironmentProfile] = field(default_factory=list)
    resources: dict[str, bytes] = field(default_factory=dict)
    description: str = ""
    labels: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> Project:
        root = root.resolve()
        manifest_path = root / "oiw.yaml"
        if not manifest_path.exists():
            raise ProjectError(f"not an OIW project: {manifest_path} not found")
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ProjectError(f"oiw.yaml is invalid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise ProjectError("oiw.yaml: top-level must be a mapping")

        api = data.get("apiVersion")
        kind = data.get("kind")
        if api != "oiw.dev/v1alpha1":
            raise ProjectError(f"oiw.yaml: unsupported apiVersion {api!r}; expected 'oiw.dev/v1alpha1'")
        if kind != "IntegrationProject":
            raise ProjectError(f"oiw.yaml: unsupported kind {kind!r}; expected 'IntegrationProject'")

        meta = data.get("metadata", {}) or {}
        spec = data.get("spec", {}) or {}

        project = cls(
            id=meta.get("id", root.name),
            name=meta.get("name", root.name),
            created=meta.get("created", "1970-01-01T00:00:00Z"),
            spec=spec,
            root=root,
            description=meta.get("description", ""),
            labels=meta.get("labels", {}) or {},
        )

        # Load flows
        flows_dir = root / "flows"
        if flows_dir.is_dir():
            for flow_dir in sorted(flows_dir.iterdir()):
                if not flow_dir.is_dir():
                    continue
                flow_file = flow_dir / "flow.yaml"
                if not flow_file.exists():
                    continue
                project.flows.append(_load_flow(flow_dir, flow_file))

        # Load tests
        for flow in project.flows:
            tests_dir = flow.source_path.parent / "tests" if flow.source_path else None
            if tests_dir and tests_dir.is_dir():
                for test_file in sorted(tests_dir.glob("*.yaml")):
                    if test_file.name == "fixtures":
                        continue
                    project.tests.append(_load_test(test_file, flow.id))

        # Load environments
        env_dir = root / "environments"
        if env_dir.is_dir():
            for env_file in sorted(env_dir.glob("*.yaml")):
                project.environments.append(_load_env(env_file))

        # Index resources
        project.resources = _index_resources(root)

        return project

    def get_flow(self, flow_id: str) -> IntegrationFlow:
        for f in self.flows:
            if f.id == flow_id:
                return f
        raise ProjectError(f"flow not found: {flow_id}")

    def get_resource(self, path: str) -> bytes | None:
        return self.resources.get(path)

    def get_test(self, name: str) -> FlowTest | None:
        for t in self.tests:
            if t.name == name:
                return t
        return None


def _load_flow(flow_dir: Path, flow_file: Path) -> IntegrationFlow:
    try:
        data = yaml.safe_load(flow_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProjectError(f"{flow_file}: invalid YAML: {exc}") from exc

    if data.get("apiVersion") != "oiw.dev/v1alpha1":
        raise ProjectError(f"{flow_file}: unsupported apiVersion")
    if data.get("kind") != "IntegrationFlow":
        raise ProjectError(f"{flow_file}: unsupported kind")

    meta = data.get("metadata", {}) or {}
    spec = data.get("spec", {}) or {}

    entrypoints = [
        Entrypoint(
            id=e["id"],
            type=e["type"],
            config=e.get("config", {}) or {},
            fidelity=e.get("fidelity", "simulated"),
        )
        for e in spec.get("entrypoints", []) or []
    ]

    nodes = [
        FlowNode(
            id=n["id"],
            type=n["type"],
            config=n.get("config", {}) or {},
            fidelity=n.get("fidelity", "simulated"),
        )
        for n in spec.get("nodes", []) or []
    ]

    edges = [
        FlowEdge(from_=e["from"], to=e["to"], condition=e.get("condition"))
        for e in spec.get("edges", []) or []
    ]

    err_handling = None
    eh = spec.get("errorHandling") or {}
    if eh.get("defaultExceptionSubprocess"):
        steps_data = eh["defaultExceptionSubprocess"].get("steps", []) or []
        steps = [
            FlowNode(
                id=s["id"],
                type=s["type"],
                config=s.get("config", {}) or {},
                fidelity=s.get("fidelity", "simulated"),
            )
            for s in steps_data
        ]
        err_handling = ErrorSubprocess(steps=steps)

    flow = IntegrationFlow(
        id=meta["id"],
        name=meta.get("name", meta["id"]),
        version=meta.get("version", 1),
        entrypoints=entrypoints,
        nodes=nodes,
        edges=edges,
        error_handling=err_handling,
        extensions=spec.get("extensions", {}) or {},
        labels=meta.get("labels", {}) or {},
        generated_by=meta.get("generatedBy"),
        source_path=flow_file,
    )

    # Load diagram
    diagram_path = flow_dir / "diagram.json"
    if diagram_path.exists():
        import json

        try:
            flow.diagram = json.loads(diagram_path.read_text(encoding="utf-8"))
        except Exception:
            flow.diagram = None

    return flow


def _load_test(test_file: Path, default_flow: str) -> FlowTest:
    try:
        data = yaml.safe_load(test_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProjectError(f"{test_file}: invalid YAML: {exc}") from exc
    meta = data.get("metadata", {}) or {}
    spec = data.get("spec", {}) or {}
    return FlowTest(
        name=meta["name"],
        flow=spec.get("flow", default_flow),
        input=spec.get("input", {}) or {},
        assertions=spec.get("assertions", []) or [],
        mocks=spec.get("mocks", []) or [],
        description=meta.get("description", ""),
        source_path=test_file,
    )


def _load_env(env_file: Path) -> EnvironmentProfile:
    try:
        data = yaml.safe_load(env_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProjectError(f"{env_file}: invalid YAML: {exc}") from exc
    meta = data.get("metadata", {}) or {}
    spec = data.get("spec", {}) or {}
    return EnvironmentProfile(
        name=meta["name"],
        target=spec.get("target", ""),
        auth=spec.get("auth", {}) or {},
        deployment_policy=spec.get("deploymentPolicy", {}) or {},
        tenant_url=spec.get("tenantUrl"),
        externalized_parameters=spec.get("externalizedParameters", {}) or {},
        source_path=env_file,
    )


def _index_resources(root: Path) -> dict[str, bytes]:
    """Index resource files by their project-relative path.

    Resources live under flows/<flow>/resources/ (spec §11.1).
    """
    resources: dict[str, bytes] = {}
    flows_dir = root / "flows"
    if not flows_dir.is_dir():
        return resources
    for flow_dir in flows_dir.iterdir():
        if not flow_dir.is_dir():
            continue
        res_dir = flow_dir / "resources"
        if not res_dir.is_dir():
            continue
        for path in res_dir.rglob("*"):
            if path.is_file():
                rel = path.relative_to(root).as_posix()
                resources[rel] = path.read_bytes()
    return resources
