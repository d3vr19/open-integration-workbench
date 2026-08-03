"""JSON Schema validation for the canonical IR.

Spec ref: §7 (IR), §14 (validation), §22 DoD (schema changes versioned).
"""

from __future__ import annotations

import dataclasses
import functools
import importlib.resources
import json
from pathlib import Path
from typing import Any

import jsonschema

from .project import EnvironmentProfile, FlowTest, IntegrationFlow, Project


class SchemaError(Exception):
    """Raised when schema files cannot be loaded."""


@dataclasses.dataclass
class SchemaValidationResult:
    errors: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)


_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "packages" / "ir-schema" / "schemas"

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}


def _load_schema(name: str) -> dict[str, Any]:
    if name in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[name]
    path = _SCHEMA_DIR / name
    if not path.exists():
        # Fallback: package-relative (for installed CLI)
        try:
            ref = importlib.resources.files("oiw.data.schemas").joinpath(name)
            with importlib.resources.as_file(ref) as p:
                path = Path(p)
        except Exception as exc:
            raise SchemaError(f"schema {name} not found: {exc}") from exc
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaError(f"schema {name}: invalid JSON: {exc}") from exc
    _SCHEMA_CACHE[name] = schema
    return schema


@functools.lru_cache(maxsize=1)
def _project_schema() -> dict[str, Any]:
    return _load_schema("oiw-project.json")


@functools.lru_cache(maxsize=1)
def _flow_schema() -> dict[str, Any]:
    return _load_schema("integration-flow.json")


@functools.lru_cache(maxsize=1)
def _test_schema() -> dict[str, Any]:
    return _load_schema("flow-test.json")


@functools.lru_cache(maxsize=1)
def _env_schema() -> dict[str, Any]:
    return _load_schema("environment-profile.json")


def _validate(instance: Any, schema: dict[str, Any], label: str) -> list[str]:
    try:
        jsonschema.validate(instance, schema)
        return []
    except jsonschema.ValidationError as exc:
        path = ".".join(str(p) for p in exc.absolute_path) or "<root>"
        return [f"{label}: {exc.message} (at {path})"]


def validate_project(project: Project) -> SchemaValidationResult:
    """Validate the project manifest, every flow, every test, and every environment."""
    result = SchemaValidationResult()

    # Project manifest
    manifest_instance = _project_to_dict(project)
    result.errors.extend(_validate(manifest_instance, _project_schema(), f"oiw.yaml ({project.id})"))

    # Flows
    for flow in project.flows:
        flow_instance = _flow_to_dict(flow)
        result.errors.extend(_validate(flow_instance, _flow_schema(), f"flow '{flow.id}' (flow.yaml)"))

    # Tests
    for test in project.tests:
        test_instance = _test_to_dict(test)
        result.errors.extend(_validate(test_instance, _test_schema(), f"test '{test.name}'"))

    # Environments
    for env in project.environments:
        env_instance = _env_to_dict(env)
        result.errors.extend(_validate(env_instance, _env_schema(), f"environment '{env.name}'"))

    return result


def _project_to_dict(project: Project) -> dict[str, Any]:
    return {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationProject",
        "metadata": {
            "id": project.id,
            "name": project.name,
            "created": project.created,
            "description": project.description or None,
            "labels": project.labels or None,
        },
        "spec": project.spec,
    }


def _flow_to_dict(flow: IntegrationFlow) -> dict[str, Any]:
    nodes = [{"id": n.id, "type": n.type, "config": n.config, "fidelity": n.fidelity} for n in flow.nodes]
    edges = [
        {"from": e.from_, "to": e.to, **({"condition": e.condition} if e.condition else {})}
        for e in flow.edges
    ]
    entrypoints = [
        {"id": e.id, "type": e.type, "config": e.config, "fidelity": e.fidelity} for e in flow.entrypoints
    ]
    spec: dict[str, Any] = {
        "entrypoints": entrypoints,
        "nodes": nodes,
        "edges": edges,
        "extensions": flow.extensions,
    }
    if flow.error_handling:
        spec["errorHandling"] = {
            "defaultExceptionSubprocess": {
                "steps": [
                    {"id": s.id, "type": s.type, "config": s.config, "fidelity": s.fidelity}
                    for s in flow.error_handling.steps
                ]
            }
        }
    meta: dict[str, Any] = {"id": flow.id, "name": flow.name, "version": flow.version, "labels": flow.labels}
    if flow.generated_by:
        meta["generatedBy"] = flow.generated_by
    return {"apiVersion": "oiw.dev/v1alpha1", "kind": "IntegrationFlow", "metadata": meta, "spec": spec}


def _test_to_dict(test: FlowTest) -> dict[str, Any]:
    return {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "FlowTest",
        "metadata": {"name": test.name, "description": test.description or None},
        "spec": {
            "flow": test.flow,
            "input": test.input,
            "mocks": test.mocks,
            "assertions": test.assertions,
        },
    }


def _env_to_dict(env: EnvironmentProfile) -> dict[str, Any]:
    return {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "EnvironmentProfile",
        "metadata": {"name": env.name},
        "spec": {
            "target": env.target,
            "tenantUrl": env.tenant_url,
            "auth": env.auth,
            "externalizedParameters": env.externalized_parameters,
            "deploymentPolicy": env.deployment_policy,
        },
    }
