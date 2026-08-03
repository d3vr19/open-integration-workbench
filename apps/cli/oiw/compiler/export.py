"""Deterministic export compiler.

Spec ref: §8.4 (round-trip policy), §4.7 (deterministic builds), §11.4 (generated files).

Produces:
  dist/
    <project>-<target-profile>/
      manifest.json     # compiler version, target profile, digest, entry list
      oiw.yaml          # canonical project manifest copy
      flows/<id>/flow.yaml
      flows/<id>/diagram.json
      flows/<id>/resources/...
      environments/*.yaml
      tests/...

  .oiw/compiler.lock    # last build digest + compiler version

Determinism rules:
  - All YAML emitted with sorted keys.
  - All JSON emitted with sorted keys, 2-space indent, LF newlines.
  - File listing in manifest sorted lexicographically.
  - Resource bytes copied verbatim.
  - sha256 digest computed over a canonical concatenation of (path, sha256(path content)).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path

import yaml

from .. import __version__ as OIW_VERSION
from ..project import Project


class BuildError(Exception):
    """Raised when the build fails."""


@dataclasses.dataclass
class BuildEntry:
    path: str
    sha256: str
    bytes: int


@dataclasses.dataclass
class BuildResult:
    out_dir: Path
    manifest_path: Path
    digest: str
    compiler_version: str
    target_profile: str
    entries: list[BuildEntry]


def build_artifact(project: Project, target_profile: str, out_dir: Path) -> BuildResult:
    """Compile IR to a target-profile artifact package."""
    if target_profile not in project.spec.get("targetProfiles", []):
        raise BuildError(
            f"target profile {target_profile!r} is not declared in oiw.yaml spec.targetProfiles "
            f"(declared: {project.spec.get('targetProfiles', [])})"
        )

    package_dir = out_dir / f"{project.id}-{target_profile}"
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)

    entries: list[BuildEntry] = []

    # 1. Project manifest copy
    entries.append(_write_file(package_dir, Path("oiw.yaml"), _yaml_bytes(_project_manifest(project))))

    # 2. Flows
    for flow in project.flows:
        flow_dir = package_dir / "flows" / flow.id
        flow_dir.mkdir(parents=True, exist_ok=True)
        entries.append(
            _write_file(package_dir, Path("flows") / flow.id / "flow.yaml", _yaml_bytes(_flow_manifest(flow)))
        )
        if flow.diagram is not None:
            entries.append(
                _write_file(package_dir, Path("flows") / flow.id / "diagram.json", _json_bytes(flow.diagram))
            )

        # Resources
        if flow.source_path:
            res_root = flow.source_path.parent / "resources"
            if res_root.is_dir():
                for src in res_root.rglob("*"):
                    if src.is_file():
                        rel = src.relative_to(flow.source_path.parent)
                        data = src.read_bytes()
                        entries.append(_write_file(package_dir, rel, data))

        # Tests
        if flow.source_path:
            tests_dir = flow.source_path.parent / "tests"
            if tests_dir.is_dir():
                for test_file in sorted(tests_dir.glob("*.yaml")):
                    rel = Path("flows") / flow.id / "tests" / test_file.name
                    data = test_file.read_bytes()
                    entries.append(_write_file(package_dir, rel, data))

    # 3. Environments
    for env in project.environments:
        entries.append(
            _write_file(
                package_dir,
                Path("environments") / f"{env.name}.yaml",
                _yaml_bytes(_env_manifest(env)),
            )
        )

    # 4. Sort entries lexicographically
    entries.sort(key=lambda e: e.path)

    # 5. Compute digest (canonical concatenation of path:sha256)
    digest_input = "\n".join(f"{e.path}:{e.sha256}" for e in entries).encode("utf-8")
    digest = f"sha256:{hashlib.sha256(digest_input).hexdigest()}"

    # 6. Write manifest
    manifest = {
        "compilerVersion": OIW_VERSION,
        "compilerLanguage": "python",
        "targetProfile": target_profile,
        "projectId": project.id,
        "projectName": project.name,
        "digest": digest,
        "entryCount": len(entries),
        "entries": [dataclasses.asdict(e) for e in entries],
    }
    manifest_path = package_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # 7. Write .oiw/compiler.lock
    lock_dir = project.root / ".oiw"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = {
        "compilerVersion": OIW_VERSION,
        "targetProfile": target_profile,
        "digest": digest,
        "builtAt": "1970-01-01T00:00:00Z",  # Deterministic: no real timestamps in build output
        "projectId": project.id,
    }
    (lock_dir / "compiler.lock").write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return BuildResult(
        out_dir=package_dir,
        manifest_path=manifest_path,
        digest=digest,
        compiler_version=OIW_VERSION,
        target_profile=target_profile,
        entries=entries,
    )


def _project_manifest(project: Project) -> dict:
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


def _flow_manifest(flow) -> dict:
    nodes = [{"id": n.id, "type": n.type, "config": n.config, "fidelity": n.fidelity} for n in flow.nodes]
    nodes.sort(key=lambda n: n["id"])
    edges = [
        {"from": e.from_, "to": e.to, **({"condition": e.condition} if e.condition else {})}
        for e in flow.edges
    ]
    edges.sort(key=lambda e: (e["from"], e["to"]))
    entrypoints = [
        {"id": e.id, "type": e.type, "config": e.config, "fidelity": e.fidelity} for e in flow.entrypoints
    ]
    spec: dict = {
        "entrypoints": entrypoints,
        "nodes": nodes,
        "edges": edges,
        "extensions": flow.extensions or {},
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
    meta: dict = {"id": flow.id, "name": flow.name, "version": flow.version, "labels": flow.labels or {}}
    if flow.generated_by:
        meta["generatedBy"] = flow.generated_by
    return {"apiVersion": "oiw.dev/v1alpha1", "kind": "IntegrationFlow", "metadata": meta, "spec": spec}


def _env_manifest(env) -> dict:
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


def _write_file(package_dir: Path, rel_path: Path, content: bytes) -> BuildEntry:
    """Write a file under package_dir and return its BuildEntry (rel path is package-relative)."""
    abs_path = package_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)
    return BuildEntry(
        path=rel_path.as_posix(),
        sha256=_sha256_bytes(content),
        bytes=len(content),
    )


def _yaml_bytes(data: dict) -> bytes:
    text = yaml.safe_dump(data, sort_keys=True, default_flow_style=False, allow_unicode=True)
    return text.encode("utf-8")


def _json_bytes(data: dict) -> bytes:
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
