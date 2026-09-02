"""Project scaffolding for `oiw init`.

Spec ref: §11.1 (repository structure).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .project import ProjectError


def scaffold_project(target: Path, archetype: str) -> None:
    if target.exists() and any(target.iterdir()):
        raise ProjectError(f"target directory is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)

    project_id = target.name
    project_name = project_id.replace("-", " ").title()

    # oiw.yaml
    manifest = {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationProject",
        "metadata": {
            "id": project_id,
            "name": project_name,
            "created": "1970-01-01T00:00:00Z",
            "description": f"Integration project: {project_name}",
        },
        "spec": {
            "package": "package/package.yaml",
            "targetProfiles": ["sap-cloud-integration-2026-07"],
            "minimumCompilerVersion": "0.1.0",
            "secretProvider": "local-keyring",
            "emg": {"enabled": False, "confidentialityScope": "project-private"},
        },
    }
    (target / "oiw.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=True, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    # package/
    (target / "package").mkdir(exist_ok=True)
    (target / "package" / "package.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "oiw.dev/v1alpha1",
                "kind": "Package",
                "metadata": {"id": project_id, "name": project_name},
                "spec": {"version": "0.1.0"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    # environments/
    (target / "environments").mkdir(exist_ok=True)
    for env_name in ("dev", "test", "prod"):
        env_data = {
            "apiVersion": "oiw.dev/v1alpha1",
            "kind": "EnvironmentProfile",
            "metadata": {"name": env_name},
            "spec": {
                "target": "sap-cloud-integration-2026-07",
                "tenantUrl": f"${{{env_name.upper()}_TENANT_URL}}",
                "auth": {
                    "method": "oauth2-client-credentials",
                    "tokenUrl": f"${{{env_name.upper()}_TOKEN_URL}}",
                    "clientId": f"${{{env_name.upper()}_CLIENT_ID}}",
                    "credentialRef": f"sap-{env_name}-api-client",
                },
                "externalizedParameters": {},
                "deploymentPolicy": {
                    "requiresApproval": env_name != "dev",
                    "approvers": ["integration-lead"] if env_name == "prod" else [],
                    "autoVerify": env_name == "dev",
                },
            },
        }
        (target / "environments" / f"{env_name}.yaml").write_text(
            yaml.safe_dump(env_data, sort_keys=True, allow_unicode=True),
            encoding="utf-8",
        )

    # policies/
    (target / "policies").mkdir(exist_ok=True)
    (target / "policies" / "integration-policy.yaml").write_text(
        "# Project-level policy overrides. See packages/policy-rules/ for defaults.\n# Spec ref: §14.\n",
        encoding="utf-8",
    )

    # .oiw/
    (target / ".oiw").mkdir(exist_ok=True)
    (target / ".oiw" / ".gitkeep").write_text("", encoding="utf-8")

    # .github/workflows/
    (target / ".github" / "workflows").mkdir(parents=True, exist_ok=True)

    # .gitignore
    (target / ".gitignore").write_text(
        "dist/\n.oiw/compiler.lock\n__pycache__/\n*.pyc\n.env\n",
        encoding="utf-8",
    )

    # README.md
    (target / "README.md").write_text(
        f"# {project_name}\n\nIntegration project bootstrapped with `oiw init`.\n\n"
        "See the project root `DEVELOPMENT_LOG.md` for project state, or the spec at the OIW repo.\n",
        encoding="utf-8",
    )

    # Archetype-specific seed flow
    if archetype != "empty":
        _seed_archetype(target, archetype, project_id, project_name)


def _seed_archetype(target: Path, archetype: str, project_id: str, project_name: str) -> None:
    flow_id = {
        "api-to-erp": "api-to-erp",
        "file-to-api": "file-to-api",
        "api-to-file": "api-to-file",
    }.get(archetype, archetype)
    flow_dir = target / "flows" / flow_id
    flow_dir.mkdir(parents=True, exist_ok=True)
    (flow_dir / "resources" / "scripts").mkdir(parents=True, exist_ok=True)
    (flow_dir / "resources" / "mappings").mkdir(parents=True, exist_ok=True)
    (flow_dir / "resources" / "schemas").mkdir(parents=True, exist_ok=True)
    (flow_dir / "tests" / "fixtures").mkdir(parents=True, exist_ok=True)

    flow = {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationFlow",
        "metadata": {
            "id": flow_id,
            "name": f"{project_name} — {archetype}",
            "version": 1,
            "labels": {"archetype": archetype},
        },
        "spec": {
            "entrypoints": [
                {
                    "id": "sender-http",
                    "type": "sender.http",
                    "config": {"path": f"/{flow_id}", "methods": ["POST"]},
                    "fidelity": "simulated",
                }
            ],
            "nodes": [
                {
                    "id": "log-receive",
                    "type": "log.message",
                    "config": {"level": "INFO", "message": "received request"},
                    "fidelity": "compatible-subset",
                },
                {
                    "id": "receiver-out",
                    "type": "receiver.http",
                    "config": {"url": "https://example.invalid/api", "method": "POST", "timeoutSeconds": 30},
                    "fidelity": "simulated",
                },
            ],
            "edges": [
                {"from": "sender-http", "to": "log-receive"},
                {"from": "log-receive", "to": "receiver-out"},
            ],
            "errorHandling": {
                "defaultExceptionSubprocess": {
                    "steps": [
                        {
                            "id": "error-log",
                            "type": "log.message",
                            "config": {"level": "ERROR", "message": "flow failed"},
                            "fidelity": "compatible-subset",
                        }
                    ]
                }
            },
            "extensions": {},
        },
    }
    (flow_dir / "flow.yaml").write_text(
        yaml.safe_dump(flow, sort_keys=True, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    # diagram.json (minimal — spec §7.3 rule 4: layout separation)
    import json

    diagram = {
        "nodes": [
            {"id": "sender-http", "position": {"x": 0, "y": 200}, "lane": "sender"},
            {"id": "log-receive", "position": {"x": 250, "y": 200}, "lane": "process"},
            {"id": "receiver-out", "position": {"x": 500, "y": 200}, "lane": "receiver"},
        ],
        "edges": [
            {"from": "sender-http", "to": "log-receive"},
            {"from": "log-receive", "to": "receiver-out"},
        ],
    }
    (flow_dir / "diagram.json").write_text(json.dumps(diagram, indent=2) + "\n", encoding="utf-8")

    # A trivial test
    test = {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "FlowTest",
        "metadata": {
            "name": "smoke",
            "description": "Scaffold smoke test: exchange completes, core step executes.",
        },
        "spec": {
            "flow": flow_id,
            "input": {
                "entrypoint": "sender-http",
                "bodyInline": "{}",
                "headers": {"Content-Type": "application/json"},
            },
            "mocks": [{"target": "receiver-out", "respond": {"status": 200, "body": "{}"}}],
            "assertions": [
                {"type": "exchange.status", "equals": "COMPLETED"},
                {"type": "node.executed", "node": "log-receive"},
            ],
        },
    }
    (flow_dir / "tests" / "smoke.yaml").write_text(
        yaml.safe_dump(test, sort_keys=True, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
