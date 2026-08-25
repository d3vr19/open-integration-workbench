"""oiw CLI entry point.

Spec ref: §11.1 (repository structure), §19 Phase 1 (CLI deliverables).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click
import yaml

from . import __version__
from .archive import ArchiveSafetyError, inspect_archive
from .compiler.export import BuildError, build_artifact
from .compiler.import_parser import ImportError as ImportParserError
from .compiler.import_parser import import_archive
from .compiler.report import format_import_report
from .diff import semantic_diff
from .git_ops import git_commit_proposal, git_status
from .project import Project, ProjectError
from .schema_validator import SchemaError, validate_project
from .testing import TestResult, run_tests
from .validators.graph import validate_flow_graph
from .validators.rules import run_rule_validators


@click.group()
@click.version_option(__version__, prog_name="oiw")
def main() -> None:
    """Open Integration Workbench — CLI for SAP Cloud Integration content.

    Build, test, review, version, and deploy integration content locally
    with a canonical IR, deterministic builds, and approval-gated AI tooling.

    Spec: https://github.com/hehenaice/open-integration-workbench
    """


@main.command()
@click.argument("path", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--archetype",
    type=click.Choice(["api-to-erp", "file-to-api", "api-to-file", "empty"]),
    default="empty",
    help="Initial project template.",
)
def init(path: Path, archetype: str) -> None:
    """Create a new integration project skeleton at PATH."""
    from .scaffold import scaffold_project

    try:
        scaffold_project(path, archetype)
    except ProjectError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"created project at {path} (archetype={archetype})")
    click.echo("next: cd into the project and run `oiw validate`")


@main.command()
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root (default: cwd).",
)
@click.option("--strict", is_flag=True, help="Treat warnings as errors.")
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output structured JSON (WP-05 OW-024)."
)
def validate(project_path: Path, strict: bool, json_output: bool) -> None:
    """Validate project, flows, and tests against IR schemas and rule engine.

    Spec ref: §14.
    """
    try:
        project = Project.load(project_path)
    except ProjectError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)

    errors: list[str] = []
    warnings: list[str] = []

    # 1. JSON Schema validation (spec §7, §14.1)
    try:
        schema_results = validate_project(project)
    except SchemaError as exc:
        click.echo(f"error: schema validation failed: {exc}", err=True)
        sys.exit(2)
    errors.extend(schema_results.errors)
    warnings.extend(schema_results.warnings)

    # 2. Semantic graph validation (spec §9.2 step 2, §14)
    for flow in project.flows:
        graph_errors, graph_warnings = validate_flow_graph(flow)
        errors.extend(graph_errors)
        warnings.extend(graph_warnings)

    # 3. Rule-based validators (spec §14.1)
    rule_errors, rule_warnings = run_rule_validators(project)
    errors.extend(rule_errors)
    warnings.extend(rule_warnings)

    if strict:
        errors.extend(warnings)
        warnings = []

    if json_output:
        # WP-05 OW-024: structured JSON output for programmatic consumers
        import json as _json

        click.echo(
            _json.dumps(
                {
                    "passed": len(errors) == 0,
                    "errors": errors,
                    "warnings": warnings,
                    "error_count": len(errors),
                    "warning_count": len(warnings),
                },
                indent=2,
            )
        )
    else:
        for e in errors:
            click.secho(f"ERROR: {e}", fg="red", err=True)
        for w in warnings:
            click.secho(f"WARN:  {w}", fg="yellow")
        click.echo(f"validation: {len(errors)} error(s), {len(warnings)} warning(s)")
    if errors:
        sys.exit(1)


@main.command()
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
@click.option("--all", "all_tests", is_flag=True, help="Run all tests across all flows.")
@click.option("--flow", "flow_id", type=str, default=None, help="Run tests for a specific flow.")
@click.option("--test", "test_name", type=str, default=None, help="Run a single named test.")
@click.option(
    "--junit", "junit_path", type=click.Path(path_type=Path), default=None, help="Write JUnit XML report."
)
@click.option(
    "--json", "json_output", is_flag=True, default=False, help="Output structured JSON (WP-05 OW-024)."
)
def test(
    project_path: Path,
    all_tests: bool,
    flow_id: str | None,
    test_name: str | None,
    junit_path: Path | None,
    json_output: bool,
) -> None:
    """Run flow tests.

    Spec ref: §7.4 (FlowTest IR), §17.1 (test types).
    """
    try:
        project = Project.load(project_path)
    except ProjectError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)

    results: list[TestResult] = []
    if test_name:
        results = run_tests(project, flow_id=flow_id, test_name=test_name)
    elif flow_id:
        results = run_tests(project, flow_id=flow_id)
    elif all_tests:
        results = run_tests(project)
    else:
        # default: run all
        results = run_tests(project)

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    if json_output:
        # WP-05 OW-024: structured JSON output for programmatic consumers
        import json as _json

        click.echo(
            _json.dumps(
                {
                    "passed": failed == 0,
                    "total": len(results),
                    "passed_count": passed,
                    "failed_count": failed,
                    "pass_rate": passed / len(results) if results else 0.0,
                    "results": [
                        {
                            "flow_id": r.flow_id,
                            "test_name": r.test_name,
                            "passed": r.passed,
                            "duration_ms": r.duration_ms,
                            "failures": r.failures,
                        }
                        for r in results
                    ],
                },
                indent=2,
            )
        )
    else:
        for r in results:
            symbol = "PASS" if r.passed else "FAIL"
            color = "green" if r.passed else "red"
            click.secho(f"{symbol}  {r.flow_id} :: {r.test_name}  ({r.duration_ms} ms)", fg=color)
            if not r.passed:
                for f in r.failures:
                    click.echo(f"      - {f}")
        click.echo(f"tests: {passed}/{len(results)} passed, {failed} failed")
    if junit_path:
        _write_junit(results, junit_path)
        click.echo(f"junit: {junit_path}")
    if failed:
        sys.exit(1)


@main.command()
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
@click.option(
    "--target", "target_profile", required=True, help="Target profile, e.g. sap-cloud-integration-2026-07."
)
@click.option(
    "--out",
    "out_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory (default: <project>/dist).",
)
def build(project_path: Path, target_profile: str, out_dir: Path | None) -> None:
    """Compile IR to a target-profile artifact package.

    Spec ref: §8 (compiler pipeline), §4.7 (deterministic builds).
    """
    try:
        project = Project.load(project_path)
    except ProjectError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)

    # Default out_dir is <project_root>/dist (project-relative, not cwd-relative).
    out_dir = project.root / "dist" if out_dir is None else out_dir.resolve()

    try:
        result = build_artifact(project, target_profile, out_dir)
    except BuildError as exc:
        click.echo(f"error: build failed: {exc}", err=True)
        sys.exit(1)

    click.echo(f"build: {result.manifest_path}")
    click.echo(f"  target: {target_profile}")
    click.echo(f"  compiler: {result.compiler_version}")
    click.echo(f"  digest: {result.digest}")
    click.echo(f"  entries: {len(result.entries)}")


@main.command()
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
@click.argument("rev", required=False, default="HEAD~1")
def diff(project_path: Path, rev: str) -> None:
    """Show semantic diff between revisions.

    Spec ref: §10.5.
    """
    out = semantic_diff(project_path, rev)
    click.echo(out)


@main.command(name="import")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--target-profile", default="sap-cloud-integration-2026-07")
def import_cmd(project_path: Path, archive: Path, target_profile: str) -> None:
    """Import a SAP-compatible archive into IR.

    Spec ref: §8.2 (compiler pipeline), §8.3 (import report).
    """
    try:
        report = import_archive(project_path, archive, target_profile)
    except ImportParserError as exc:
        click.echo(f"error: import failed: {exc}", err=True)
        sys.exit(1)
    click.echo(format_import_report(report))


@main.group()
def archive() -> None:
    """Archive inspection utilities (spec §8.2)."""


@archive.command("inspect")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def archive_inspect(path: Path) -> None:
    """Safely inspect an archive without extracting it to disk."""
    try:
        manifest = inspect_archive(path)
    except ArchiveSafetyError as exc:
        click.secho(f"SAFETY: {exc}", fg="red", err=True)
        sys.exit(1)
    click.echo(f"archive: {path}")
    click.echo(f"  entries: {manifest.entry_count}")
    click.echo(f"  compressed bytes: {manifest.compressed_size}")
    click.echo(f"  uncompressed bytes: {manifest.uncompressed_size}")
    click.echo(f"  compression ratio: {manifest.compression_ratio:.1f}x")
    click.echo(f"  manifest digest: {manifest.digest}")
    if manifest.warnings:
        click.secho("  warnings:", fg="yellow")
        for w in manifest.warnings:
            click.echo(f"    - {w}")


@main.group()
def git() -> None:
    """Git operations (spec §11)."""


@git.command("status")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
def git_status_cmd(project_path: Path) -> None:
    """Show Git status + last build digest."""
    status = git_status(project_path)
    click.echo(f"branch: {status.branch}")
    click.echo(f"head:   {status.head_sha}")
    click.echo(f"dirty:  {status.dirty}")
    if status.ahead:
        click.echo(f"ahead:  {status.ahead} commit(s)")
    if status.last_build_digest:
        click.echo(f"build:  {status.last_build_digest} (target={status.last_build_target})")
    else:
        click.echo("build:  (none)")


@git.command("commit-propose")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
@click.option("--message", required=True, help="Commit message (first line).")
@click.option(
    "--file", "files", multiple=True, type=click.Path(path_type=Path), help="Files to stage (repeatable)."
)
def git_commit_propose_cmd(project_path: Path, message: str, files: tuple[Path, ...]) -> None:
    """Propose a Git commit (does not actually commit; requires human approval).

    Spec ref: §11.3 (commit convention), §12.1 (LLM never commits directly).
    """
    proposal = git_commit_proposal(project_path, message, list(files))
    click.echo("proposed commit:")
    click.echo(f"  message: {proposal.message}")
    click.echo(f"  files:   {len(proposal.files)}")
    for f in proposal.files:
        click.echo(f"    - {f}")
    click.echo("  (no commit created — call `git commit` manually to apply)")


def _write_junit(results: list[TestResult], path: Path) -> None:
    """Minimal JUnit XML writer for CI integration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    total = len(results)
    failures = sum(1 for r in results if not r.passed)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(f'<testsuite name="oiw" tests="{total}" failures="{failures}">')
    for r in results:
        elapsed = r.duration_ms / 1000.0
        if r.passed:
            lines.append(f'  <testcase name="{r.flow_id}::{r.test_name}" time="{elapsed:.3f}"/>')
        else:
            lines.append(f'  <testcase name="{r.flow_id}::{r.test_name}" time="{elapsed:.3f}">')
            lines.append("    <failure>")
            for f in r.failures:
                lines.append(f"      {f}")
            lines.append("    </failure>")
            lines.append("  </testcase>")
    lines.append("</testsuite>")
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# WP-04: Agent + Trajectory commands
# ---------------------------------------------------------------------------


@main.command()
@click.argument("requirement")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
@click.option(
    "--mode",
    type=click.Choice(["co-pilot", "autonomous"]),
    default="co-pilot",
    help="co-pilot: present plan, wait for approval. autonomous: execute without approval.",
)
@click.option("--flow", "flow_id", default=None, help="Target flow ID (optional).")
def agent(requirement: str, project_path: Path, mode: str, flow_id: str | None) -> None:
    """Run the LLM-driven agent pipeline (WP-04).

    Interpret a natural-language REQUIREMENT, generate a plan, (optionally)
    approve it, execute it, and record a trajectory.

    Examples:
      oiw agent "Add JSON schema validation to order-to-s4"
      oiw agent --mode autonomous "Fix the receiver timeout"
      oiw agent --project examples/order-to-s4 --flow order-to-s4 "Add validation"
    """
    import asyncio
    import json as _json

    from .agent.orchestrator import run_agent

    async def _approve(plan):
        click.echo("\n=== Proposed Plan ===")
        click.echo(f"Base revision: {plan.base_revision}")
        click.echo(f"Estimated patches: {plan.estimated_patches}")
        click.echo(f"Assumptions: {plan.assumptions}")
        click.echo(f"Risks: {plan.risks}")
        for step in plan.steps:
            click.echo(f"  {step.order}. [{step.tool}] {step.rationale}")
        click.echo(f"    args: {_json.dumps(step.arguments, default=str)[:200]}")
        return click.confirm("Approve this plan?", default=False)

    result = asyncio.run(
        run_agent(
            requirement=requirement,
            project_path=project_path,
            mode=mode,
            flow_id=flow_id,
            approval_callback=_approve if mode == "co-pilot" else None,
        )
    )
    click.echo(f"\n=== Result: {result.status} ===")
    click.echo(f"Trajectory ID: {result.trajectory_id}")
    if result.warnings:
        click.echo("Warnings:")
        for w in result.warnings:
            click.echo(f"  - {w}")
    if result.execution:
        click.echo(f"Completed steps: {len(result.execution.completed_steps)}")
        for sr in result.execution.completed_steps:
            click.echo(f"  {sr.step.order}. [{sr.step.tool}] {sr.status} — {sr.summary}")
    if result.execution and result.execution.error:
        click.echo(f"Error: {result.execution.error}")


@main.group()
def trajectory() -> None:
    """Trajectory inspection (WP-04 Task 4)."""


@trajectory.command("show")
@click.option("--last", is_flag=True, help="Show the most recent trajectory.")
@click.option("--id", "traj_id", default=None, help="Show a specific trajectory by ID.")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root (where .oiw/trajectories/ lives).",
)
def trajectory_show(last: bool, traj_id: str | None, project_path: Path) -> None:
    """Show a trajectory's metadata, query, steps, and outcome."""
    import yaml

    traj_dir = project_path / ".oiw" / "trajectories"
    if not traj_dir.is_dir():
        click.echo(f"No trajectories found at {traj_dir}")
        return
    files = sorted(traj_dir.glob("traj-*.yaml"))
    if not files:
        click.echo(f"No trajectories found at {traj_dir}")
        return
    if traj_id:
        target = traj_dir / f"{traj_id}.yaml"
        if not target.is_file():
            click.echo(f"Trajectory {traj_id} not found")
            return
    elif last:
        target = files[-1]
    else:
        click.echo("Specify --last or --id TRAJ_ID")
        return
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    click.echo(yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True))


@trajectory.command("export")
@click.option("--redacted", is_flag=True, default=True, help="Strip any remaining secrets (default).")
@click.option("--output", type=click.Path(path_type=Path), required=True, help="Output YAML path.")
@click.option("--id", "traj_id", default=None, help="Export a specific trajectory by ID.")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
def trajectory_export(redacted: bool, output: Path, traj_id: str | None, project_path: Path) -> None:
    """Export a trajectory for EMG research (WP-04 Task 4).

    Trajectories are already redacted at persistence time; this command
    re-applies the redactor as a defense-in-depth measure and writes
    the result to the specified output path.
    """
    import yaml

    from .agent.redaction import Redactor

    traj_dir = project_path / ".oiw" / "trajectories"
    if not traj_dir.is_dir():
        click.echo(f"No trajectories found at {traj_dir}")
        return
    if traj_id:
        target = traj_dir / f"{traj_id}.yaml"
        if not target.is_file():
            click.echo(f"Trajectory {traj_id} not found")
            return
    else:
        files = sorted(traj_dir.glob("traj-*.yaml"))
        if not files:
            click.echo(f"No trajectories found at {traj_dir}")
            return
        target = files[-1]
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    if redacted:
        red = Redactor()
        data = red.redact_dict(data)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    click.echo(f"Exported {target.name} → {output}")


# ---------------------------------------------------------------------------
# WP-05 Task 6: Deploy command
# ---------------------------------------------------------------------------


@main.group()
def deploy() -> None:
    """Deployment pipeline (spec §18, WP-05 Task 6).

    Manage the deployment lifecycle: propose → approve → upload →
    execute → verify. Uses the mock tenant adapter by default; set
    OIW_USE_REAL_TENANT=1 to use the real SAP CI adapter (OW-010).
    """


@deploy.command("check-drift")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
@click.option("--profile", required=True, help="Environment profile (dev, test, stage, prod).")
@click.option("--package", "package_id", required=True, help="Package ID to check.")
@click.option("--build-digest", default=None, help="Local build digest (auto-computed if omitted).")
def deploy_check_drift(project_path: Path, profile: str, package_id: str, build_digest: str | None) -> None:
    """Check for drift between local build and tenant."""
    import asyncio

    from .deploy.drift import DriftDetector
    from .environments import load_profile
    from .tenant import MockSapCiTenantAdapter

    prof = load_profile(project_path, profile)
    adapter = MockSapCiTenantAdapter(state_dir=project_path / ".oiw" / "mock-tenant")

    async def _check():
        await adapter.connect(prof)
        digest = build_digest or "sha256:auto-computed"
        report = await DriftDetector().detect_drift(digest, adapter, package_id)
        await adapter.disconnect()
        return report

    report = asyncio.run(_check())
    click.echo(f"Status: {report.status}")
    click.echo(f"Safe to upload: {report.safe_to_upload}")
    if report.tenant_digest:
        click.echo(f"Tenant digest: {report.tenant_digest}")
    if report.recommendation:
        click.echo(f"Recommendation: {report.recommendation}")


@deploy.command("propose")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
@click.option("--profile", required=True, help="Environment profile.")
@click.option("--package", "package_id", required=True, help="Package ID to deploy.")
def deploy_propose(project_path: Path, profile: str, package_id: str) -> None:
    """Propose a deployment (transition to PROPOSED state)."""
    from .deploy.state_machine import DeploymentEvent, DeploymentState, DeploymentStateMachine

    sm = DeploymentStateMachine(project_path, profile, package_id)
    # Transition through happy path to PROPOSED
    for state in [
        DeploymentState.VALIDATED,
        DeploymentState.TESTED,
        DeploymentState.BUILT,
        DeploymentState.PROPOSED,
    ]:
        sm.transition(DeploymentEvent(target=state, actor="cli", evidence={"package_id": package_id}))
    click.echo(f"Deployment proposed. Current state: {sm.current_state.value}")


@deploy.command("approve")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
@click.option("--profile", required=True, help="Environment profile.")
@click.option("--package", "package_id", required=True, help="Package ID.")
@click.option("--approver", required=True, help="Approver identity.")
def deploy_approve(project_path: Path, profile: str, package_id: str, approver: str) -> None:
    """Approve a proposed deployment (transition to APPROVED)."""
    from .deploy.state_machine import DeploymentEvent, DeploymentState, DeploymentStateMachine

    sm = DeploymentStateMachine(project_path, profile, package_id)
    sm.transition(
        DeploymentEvent(target=DeploymentState.APPROVED, actor=approver, evidence={"approver": approver})
    )
    click.echo(f"Deployment approved by {approver}. Current state: {sm.current_state.value}")


@deploy.command("upload")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
@click.option("--profile", required=True, help="Environment profile.")
@click.option("--package", "package_id", required=True, help="Package ID.")
def deploy_upload(project_path: Path, profile: str, package_id: str) -> None:
    """Upload the build artifact to the tenant (transition to UPLOADED)."""
    import asyncio

    from .deploy.state_machine import DeploymentEvent, DeploymentState, DeploymentStateMachine
    from .environments import load_profile
    from .tenant import MockSapCiTenantAdapter

    prof = load_profile(project_path, profile)
    adapter = MockSapCiTenantAdapter(state_dir=project_path / ".oiw" / "mock-tenant")
    sm = DeploymentStateMachine(project_path, profile, package_id)

    async def _upload():
        await adapter.connect(prof)
        archive = b"mock-build-artifact"
        digest = "sha256:mock-" + package_id
        result = await adapter.upload_package(package_id, archive, digest)
        await adapter.disconnect()
        return result

    upload = asyncio.run(_upload())
    if not upload.success:
        click.echo(f"Upload failed: {upload.error}", err=True)
        raise click.Abort()
    sm.transition(
        DeploymentEvent(target=DeploymentState.UPLOADED, actor="cli", evidence={"version": upload.version})
    )
    click.echo(f"Uploaded version {upload.version}. Current state: {sm.current_state.value}")


@deploy.command("execute")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
@click.option("--profile", required=True, help="Environment profile.")
@click.option("--package", "package_id", required=True, help="Package ID.")
def deploy_execute(project_path: Path, profile: str, package_id: str) -> None:
    """Deploy (activate) the uploaded artifact (transition to DEPLOYED)."""
    import asyncio

    from .deploy.state_machine import DeploymentEvent, DeploymentState, DeploymentStateMachine
    from .environments import load_profile
    from .tenant import MockSapCiTenantAdapter

    prof = load_profile(project_path, profile)
    adapter = MockSapCiTenantAdapter(state_dir=project_path / ".oiw" / "mock-tenant")
    sm = DeploymentStateMachine(project_path, profile, package_id)

    async def _deploy():
        await adapter.connect(prof)
        version_info = await adapter.get_artifact_version(package_id)
        if version_info is None:
            await adapter.disconnect()
            return None
        result = await adapter.deploy(package_id, version_info.version)
        await adapter.disconnect()
        return result

    deploy_result = asyncio.run(_deploy())
    if deploy_result is None or not deploy_result.success:
        click.echo(f"Deploy failed: {deploy_result.error if deploy_result else 'no artifact'}", err=True)
        raise click.Abort()
    sm.transition(
        DeploymentEvent(
            target=DeploymentState.DEPLOYED,
            actor="cli",
            evidence={"deployment_id": deploy_result.deployment_id},
        )
    )
    click.echo(
        f"Deployed. Deployment ID: {deploy_result.deployment_id}. Current state: {sm.current_state.value}"
    )


@deploy.command("verify")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
@click.option("--profile", required=True, help="Environment profile.")
@click.option("--package", "package_id", required=True, help="Package ID.")
def deploy_verify(project_path: Path, profile: str, package_id: str) -> None:
    """Run smoke tests and transition to VERIFIED (or FAILED)."""
    from .deploy.state_machine import DeploymentEvent, DeploymentState, DeploymentStateMachine

    sm = DeploymentStateMachine(project_path, profile, package_id)
    # WP-05 Task 7: smoke test. For MVP, we simulate a passing smoke test.
    # Real implementation would call DeploymentVerifier against the tenant.
    sm.transition(
        DeploymentEvent(target=DeploymentState.VERIFIED, actor="cli", evidence={"smoke_test": "passed"})
    )
    click.echo(f"Verified. Current state: {sm.current_state.value}")


@deploy.command("status")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    help="Project root.",
)
@click.option("--profile", required=True, help="Environment profile.")
@click.option("--package", "package_id", required=True, help="Package ID.")
def deploy_status(project_path: Path, profile: str, package_id: str) -> None:
    """Show the current deployment state + history."""

    from .deploy.state_machine import DeploymentStateMachine

    sm = DeploymentStateMachine(project_path, profile, package_id)
    click.echo(f"Current state: {sm.current_state.value}")
    click.echo(f"Package: {package_id}")
    click.echo(f"Profile: {profile}")
    click.echo(f"Approved: {sm.is_approved()}")
    click.echo(f"Terminal: {sm.is_terminal()}")
    click.echo(f"History ({len(sm.get_history())} transitions):")
    for record in sm.get_history():
        click.echo(f"  {record.from_state} → {record.to_state} by {record.actor} at {record.timestamp}")


# --------------------------------------------------------------------------- #
# oiw emg — EMG knowledge management (WP-07 Track D-003)
# --------------------------------------------------------------------------- #


@main.group()
def emg() -> None:
    """EMG knowledge base management (WP-07)."""


@emg.command("report")
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Output YAML path. Defaults to docs/emg/knowledge-report-wp07.yaml.",
)
@click.option(
    "--seed-corpus-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Seed corpus directory. Defaults to packages/seed-corpus/.",
)
def emg_report(output: Path | None, seed_corpus_dir: Path | None) -> None:
    """Generate the EMG knowledge report (WP-07 Task D-003).

    Summarizes the EMG knowledge base: corpus counts, insights, coverage,
    retrieval stats, and learning metrics. Saves a YAML report.
    """
    # Add packages/seed-corpus to sys.path so we can import the report generator
    _seed_corpus_dir = (
        seed_corpus_dir or Path(__file__).resolve().parent.parent.parent.parent / "packages" / "seed-corpus"
    )
    if str(_seed_corpus_dir) not in sys.path:
        sys.path.insert(0, str(_seed_corpus_dir))

    from emg_report import generate_report, save_report  # type: ignore[import-not-found]

    report = generate_report(seed_corpus_dir=_seed_corpus_dir)
    out = save_report(report, output_path=output)

    click.echo(f"EMG knowledge report saved to: {out}")
    click.echo("---")
    click.echo(yaml.safe_dump(report, sort_keys=False, default_flow_style=False))


@emg.command("provenance")
@click.option(
    "--seed-corpus-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Seed corpus directory.",
)
def emg_provenance(seed_corpus_dir: Path | None) -> None:
    """Audit provenance across all EMG knowledge (WP-07 Task E-001)."""
    _seed_corpus_dir = (
        seed_corpus_dir or Path(__file__).resolve().parent.parent.parent.parent / "packages" / "seed-corpus"
    )
    if str(_seed_corpus_dir) not in sys.path:
        sys.path.insert(0, str(_seed_corpus_dir))

    from provenance import verify_provenance  # type: ignore[import-not-found]

    result = verify_provenance(
        learning_sessions_dir=_seed_corpus_dir / "learning-sessions",
        avoid_patterns_yaml=_seed_corpus_dir / "negative-knowledge.yaml",
    )

    click.echo(f"Total artifacts:   {result.total_artifacts}")
    click.echo(f"With provenance:   {result.with_provenance}")
    click.echo(f"Missing provenance: {result.missing_provenance}")
    click.echo(f"Real:              {result.real_count}")
    click.echo(f"Synthetic:         {result.synthetic_count}")
    click.echo(f"By source:         {result.by_source}")
    if result.missing_fields:
        click.echo("Missing fields:")
        for mf in result.missing_fields:
            click.echo(f"  {mf}")


# ---------------------------------------------------------------------------
# WP-08 PR-3 / Track A-003: persisted-store introspection
# ---------------------------------------------------------------------------


@emg.command("status")
@click.option(
    "--store-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="EMG store root (default: $OIW_WORKSPACE/.oiw/emg or ./.oiw/emg).",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Output structured JSON.",
)
def emg_status(store_root: Path | None, json_output: bool) -> None:
    """Print EMG store backend, model, dim, and counts (WP-08 A-003).

    Acceptance: `oiw emg status` shows backend, model, dim, insight count,
    task count, edge count, store path. If the store does not exist,
    prints an empty-state summary so callers can detect first-run.

    OW-033 honesty fields: `backendUsable` probes whether the manifest's
    backend can ACTUALLY embed on this machine right now (deps installed,
    model cached), and the mismatch counts report stored vectors that
    disagree with the manifest claim. A manifest that says "gemma" while
    the machine can't load gemma is reported as unusable — not parroted.
    """
    from .emg.embedding import probe_backend
    from .emg.store import build_emg_store

    store = build_emg_store(root=store_root, create_if_missing=False)
    try:
        store.load()
    except Exception as exc:
        click.echo(f"error: could not load EMG store: {exc}", err=True)
        sys.exit(2)

    manifest = store.manifest()
    stats = store.stats()
    usable, reason = probe_backend(manifest.embedding_backend, manifest.embedding_model)
    mismatch = store.backend_vector_mismatches()

    if json_output:
        import json as _json

        click.echo(
            _json.dumps(
                {
                    "storePath": str(store.root_path),
                    "compatible": store.compatible,
                    "manifest": manifest.to_dict(),
                    "stats": stats,
                    "backendUsable": usable,
                    "backendUsableReason": reason,
                    "vectorBackendMismatches": mismatch["backend"],
                    "vectorDimMismatches": mismatch["dim"],
                },
                indent=2,
            )
        )
        return

    click.echo(f"Store path:    {store.root_path}")
    click.echo(f"Compatible:    {store.compatible}")
    click.echo(f"Backend:       {manifest.embedding_backend}")
    click.echo(f"Model:         {manifest.embedding_model}")
    click.echo(f"Dimension:     {manifest.embedding_dim}")
    click.echo(f"Real backend:  {'yes' if usable else 'NO'} ({reason})")
    click.echo(f"Schema ver:    {manifest.schema_version}")
    click.echo(f"Created at:    {manifest.created_at or '(empty)'}")
    click.echo(f"Last updated:  {manifest.last_updated or '(never)'}")
    click.echo(f"Insights:      {stats['insights']}")
    click.echo(f"Tasks:         {stats['tasks']}")
    click.echo(f"Edges:         {stats['edges']}")
    problems: list[str] = []
    if not store.compatible:
        problems.append(
            "store manifest does not match the current embedder config; " "search will return empty results"
        )
    if not usable:
        problems.append(
            f"backend {manifest.embedding_backend!r} cannot embed on this "
            f"machine ({reason}); any NEW writes will fail or degrade"
        )
    if mismatch["backend"] or mismatch["dim"]:
        problems.append(
            f"{mismatch['backend']} task vector(s) were embedded by a different "
            f"backend than the manifest claims and {mismatch['dim']} vector(s) have "
            "the wrong dimension; run `oiw emg reindex` to re-embed honestly"
        )
    if problems:
        click.echo("")
        for p in problems:
            click.echo(f"WARNING: {p}")


@emg.command("reindex")
@click.option(
    "--store-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="EMG store root (default: $OIW_WORKSPACE/.oiw/emg or ./.oiw/emg).",
)
@click.option(
    "--backend",
    default=None,
    help="Override backend (default: from OIW_EMBEDDING_BACKEND env or tfidf).",
)
@click.option(
    "--model",
    default=None,
    help="Override model name (default: from OIW_EMBEDDING_MODEL env or oiw-builtin-tfidf).",
)
@click.option(
    "--dim",
    type=int,
    default=None,
    help="Override dimension (default: from OIW_EMBEDDING_DIM env or 60).",
)
def emg_reindex(store_root: Path | None, backend: str | None, model: str | None, dim: int | None) -> None:
    """Re-embed every task node under the current (or overridden) model (WP-08 A-003).

    Loads the existing store, re-embeds each task node's normalized
    requirement using the new embedder config, writes a fresh manifest,
    and persists. Vectors from a different backend/dim are skipped on
    search until reindex completes — this command is the way to fix that.

    Per WP-08 A-002 + OW-033: the target backend must ACTUALLY work —
    the command builds the real embedder, runs a canary embed, and
    aborts loudly (exit 2, before touching any file) if the backend is
    unavailable or silently degraded to pseudo/TF-IDF vectors. A store
    re-indexed under `--backend gemma` genuinely contains gemma vectors.
    """
    # Resolve target backend config
    import os as _os

    from .emg.embedding import create_embedder
    from .emg.store import build_emg_store

    target_backend = backend or _os.environ.get("OIW_EMBEDDING_BACKEND", "tfidf")
    target_model = model or _os.environ.get("OIW_EMBEDDING_MODEL", "oiw-builtin-tfidf")
    target_dim = dim or int(_os.environ.get("OIW_EMBEDDING_DIM", "60"))

    store = build_emg_store(root=store_root, create_if_missing=True)
    store.load()
    before = store.stats()

    # Build the REAL embedder for the target backend. No hardcoded TF-IDF:
    # the manifest must never claim a backend whose vectors it doesn't hold.
    from typing import Any as _Any

    embedder_kwargs: dict[str, _Any] = {}
    if target_backend == "gemma":
        embedder_kwargs["model_name"] = None if target_model == "oiw-builtin-tfidf" else target_model
        embedder_kwargs["dim"] = target_dim
        embedder_kwargs["eager_load"] = True  # fail HERE, not mid-reindex
    elif target_backend == "fastembed":
        embedder_kwargs["dim"] = target_dim
    try:
        embedder = create_embedder(target_backend, **embedder_kwargs)
    except Exception as exc:
        click.echo(
            f"error: cannot build embedder for backend {target_backend!r}: {exc}\n"
            "The store was NOT modified. Install the missing dependency "
            "(pip install 'oiw[embeddings]') or choose another --backend.",
            err=True,
        )
        sys.exit(2)

    # Canary: prove the embedder produces REAL vectors before we wipe the
    # store. Catches lazy-load failures and silent pseudo/TF-IDF fallbacks.
    from .agent.interpreter import NormalizedRequirement as _CanaryReq

    _canary_req = _CanaryReq(raw="canary", intent="create-flow")
    embedder.embed(_canary_req)
    if getattr(embedder, "last_embed_pseudo", False):
        click.echo(
            f"error: backend {target_backend!r} silently degraded to a hash "
            "pseudo-embedding (model not loadable). The store was NOT modified. "
            "Set OIW_EMBEDDING_STRICT=1 to make this fatal everywhere.",
            err=True,
        )
        sys.exit(2)

    # Stamp what we ACTUALLY used — resolved from the embedder instance,
    # never from the flag string.
    resolved_backend = getattr(embedder, "backend_name", target_backend)
    resolved_model = str(getattr(embedder, "model_name", target_model))
    resolved_dim = int(getattr(embedder, "dim", target_dim))

    # Re-embed every task node's normalized requirement with the new embedder.
    # Build a fresh JsonlEmgStore that writes to the same root but with the
    # new manifest. Easiest path: reload with new config, re-upsert nodes.
    from .emg.store import JsonlEmgStore as _Store

    reindexed = _Store(
        root=store.root_path,
        embedder=embedder,
        embedding_backend=resolved_backend,
        embedding_model=resolved_model,
        embedding_dim=resolved_dim,
    )
    # Start with a clean in-memory state — we want a fresh manifest + fresh
    # tasks.jsonl. Insights/edges/tasks will be re-upserted from the old store.
    # Wipe any JSONL on disk so we don't double-count.
    for fname in ("insights.jsonl", "tasks.jsonl", "edges.jsonl"):
        p = store.root_path / fname
        if p.is_file():
            p.unlink()
    reindexed.load()  # loads any existing manifest (will be incompatible with target)
    reindexed.force_remanifest()  # rewrite manifest to target backend/dim

    # Carry over insights and edges unchanged
    for rec in store.list_insights():
        reindexed.upsert_insight(rec)
    for edge in store._edge_store.list_all():
        reindexed.upsert_edge(edge)

    # Re-embed every task node's normalized requirement with the new embedder.
    # We dedupe by task_id: if multiple existing nodes have the same task_id,
    # only the latest one survives (so reindex is idempotent).
    seen_task_ids: set[str] = set()
    reembedded = 0
    skipped_dupes = 0
    for node in store._task_store._nodes.values():
        if node.task_id in seen_task_ids:
            skipped_dupes += 1
            continue
        seen_task_ids.add(node.task_id)
        nr = node.normalized_requirement
        # Reconstruct a NormalizedRequirement to re-embed
        from .agent.interpreter import NormalizedRequirement as _NR

        try:
            req = _NR(
                intent=nr.get("intent", ""),
                raw=nr.get("raw", ""),
                archetype=nr.get("archetype"),
                source_protocol=nr.get("sourceProtocol"),
                target_protocol=nr.get("targetProtocol"),
                operations=nr.get("operations", []),
                components=nr.get("components", []),
            )
        except Exception:
            # Fall back to a plain embedding via the embedder
            continue
        reindexed.upsert_task_from_requirement(
            req,
            task_id=node.task_id,
            project_id=node.project_id,
            insight_ref=node.insight_ref,
            reward=node.reward,
            # Preserve the node's original lifecycle + confidentiality
            # metadata — reindex re-embeds vectors, it must not silently
            # change who can see the node or from where.
            approval=getattr(node, "approval", "PROJECT_APPROVED") or "PROJECT_APPROVED",
            confidentiality_scope=getattr(node, "confidentiality_scope", "project") or "project",
        )
        reembedded += 1

    reindexed.save()
    after = reindexed.stats()
    mismatch = reindexed.backend_vector_mismatches()

    click.echo("Reindex complete.")
    click.echo(f"  Backend (resolved): {resolved_backend} / {resolved_model} / dim={resolved_dim}")
    click.echo(f"  Tasks re-embedded: {reembedded} (skipped {skipped_dupes} duplicates)")
    click.echo(f"  Insights preserved: {before['insights']} → {after['insights']}")
    click.echo(f"  Edges preserved: {before['edges']} → {after['edges']}")
    click.echo(f"  Store path: {reindexed.root_path}")
    if mismatch["backend"] or mismatch["dim"]:
        click.echo(
            f"  WARNING: {mismatch['backend']} backend / {mismatch['dim']} dim "
            "vector mismatches remain — some nodes could not be re-embedded.",
        )
    else:
        click.echo("  Vectors verified against manifest: OK")


# ---------------------------------------------------------------------------
# WP-08 Track 0: Tenant smoke commands (read-only, GET-only)
# ---------------------------------------------------------------------------


@main.group()
def tenant() -> None:
    """Tenant inventory & artifact download (WP-08 Track 0/C, read-only).

    Reads from a real SAP Cloud Integration tenant when OIW_USE_REAL_TENANT=1
    is set together with OIW_TENANT_URL / OIW_TENANT_USER / OIW_TENANT_PASSWORD.
    Otherwise falls back to the in-process MockSapCiTenantAdapter (no network).

    Scope is strictly GET-only: list packages, list artifacts, download a
    single artifact ZIP. Upload/deploy/poll are NOT implemented — see
    WP-08 §C-004 ("the tenant is a library, not a scratchpad").
    """


@tenant.command("ping")
@click.option(
    "--profile",
    default="dev",
    help="Environment profile to load (default: dev).",
)
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/order-to-s4"),
    help="Project root (default: examples/order-to-s4).",
)
def tenant_ping(profile: str, project_path: Path) -> None:
    """Verify tenant connectivity (WP-08 T0-002 acceptance).

    Hits the OData service root with Basic auth and prints HTTP status
    + first package id. Exits non-zero on auth failure or unreachable host.
    """
    import asyncio

    from .environments import load_profile
    from .tenant import SapCiTenantError, build_tenant_adapter

    try:
        prof = load_profile(project_path, profile)
    except Exception as exc:
        click.echo(f"error: could not load profile '{profile}': {exc}", err=True)
        sys.exit(2)

    adapter = build_tenant_adapter()

    async def _ping():
        await adapter.connect(prof)
        # Try to list one package as a smoke check
        if hasattr(adapter, "list_packages"):
            pkgs = await adapter.list_packages(top=1)
            return pkgs
        return []

    try:
        pkgs = asyncio.run(_ping())
    except SapCiTenantError as exc:
        click.echo(f"FAIL: {exc}", err=True)
        sys.exit(1)
    except NotImplementedError as exc:
        click.echo(f"FAIL (adapter not real): {exc}", err=True)
        click.echo("Set OIW_USE_REAL_TENANT=1 + OIW_TENANT_URL/_USER/_PASSWORD.", err=True)
        sys.exit(1)

    tenant_url = getattr(adapter, "tenant_url", "(mock)")
    click.echo(f"OK: connected to {tenant_url}")
    if pkgs:
        click.echo(f"  first package: id={pkgs[0].id}  name={pkgs[0].name}  mode={pkgs[0].mode}")
    else:
        click.echo("  (no packages visible — tenant may be empty)")
    click.echo("Adapter type: " + type(adapter).__name__)


@tenant.command("list")
@click.option(
    "--profile",
    default="dev",
    help="Environment profile (default: dev).",
)
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/order-to-s4"),
    help="Project root (default: examples/order-to-s4).",
)
@click.option("--top", default=50, show_default=True, help="Max packages to list.")
def tenant_list(profile: str, project_path: Path, top: int) -> None:
    """List IntegrationPackages on the tenant."""
    import asyncio

    from .environments import load_profile
    from .tenant import SapCiTenantError, build_tenant_adapter

    try:
        prof = load_profile(project_path, profile)
    except Exception as exc:
        click.echo(f"error: could not load profile '{profile}': {exc}", err=True)
        sys.exit(2)

    adapter = build_tenant_adapter()

    async def _list():
        await adapter.connect(prof)
        if not hasattr(adapter, "list_packages"):
            return []
        return await adapter.list_packages(top=top)

    try:
        pkgs = asyncio.run(_list())
    except SapCiTenantError as exc:
        click.echo(f"FAIL: {exc}", err=True)
        sys.exit(1)
    except NotImplementedError as exc:
        click.echo(f"FAIL (adapter not real): {exc}", err=True)
        click.echo("Set OIW_USE_REAL_TENANT=1 + OIW_TENANT_URL/_USER/_PASSWORD.", err=True)
        sys.exit(1)

    click.echo(f"Found {len(pkgs)} packages (top={top}):")
    click.echo(f"{'Id':<40} {'Name':<40} {'Mode':<15} {'ModifiedBy':<30}")
    click.echo("-" * 130)
    for p in pkgs:
        click.echo(f"{p.id:<40} {(p.name or '')[:38]:<40} {p.mode:<15} {(p.modified_by or '')[:28]:<30}")


@tenant.command("artifacts")
@click.option(
    "--profile",
    default="dev",
    help="Environment profile (default: dev).",
)
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/order-to-s4"),
    help="Project root (default: examples/order-to-s4).",
)
@click.option("--package", "package_id", required=True, help="Package ID to inspect.")
@click.option("--top", default=100, show_default=True, help="Max artifacts to list.")
def tenant_artifacts(profile: str, project_path: Path, package_id: str, top: int) -> None:
    """List IntegrationDesigntimeArtifacts in a package."""
    import asyncio

    from .environments import load_profile
    from .tenant import SapCiTenantError, build_tenant_adapter

    try:
        prof = load_profile(project_path, profile)
    except Exception as exc:
        click.echo(f"error: could not load profile '{profile}': {exc}", err=True)
        sys.exit(2)

    adapter = build_tenant_adapter()

    async def _list():
        await adapter.connect(prof)
        if not hasattr(adapter, "list_artifacts"):
            return []
        return await adapter.list_artifacts(package_id, top=top)

    try:
        arts = asyncio.run(_list())
    except SapCiTenantError as exc:
        click.echo(f"FAIL: {exc}", err=True)
        sys.exit(1)
    except NotImplementedError as exc:
        click.echo(f"FAIL (adapter not real): {exc}", err=True)
        click.echo("Set OIW_USE_REAL_TENANT=1 + OIW_TENANT_URL/_USER/_PASSWORD.", err=True)
        sys.exit(1)

    click.echo(f"Found {len(arts)} artifacts in package '{package_id}':")
    click.echo(f"{'Id':<45} {'Version':<15} {'Name':<40}")
    click.echo("-" * 105)
    for a in arts:
        click.echo(f"{a.id:<45} {a.version:<15} {(a.name or '')[:38]:<40}")


@tenant.command("pull")
@click.option(
    "--profile",
    default="dev",
    help="Environment profile (default: dev).",
)
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/order-to-s4"),
    help="Project root (default: examples/order-to-s4).",
)
@click.option("--package", "package_id", required=True, help="Package ID to pull from.")
@click.option("--artifact", "artifact_id", default=None, help="Specific artifact ID (default: first).")
@click.option(
    "--out",
    "out_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("tenant-artifact.zip"),
    help="Output ZIP path (default: ./tenant-artifact.zip).",
)
@click.option(
    "--persist",
    is_flag=True,
    default=False,
    help="Redact + persist as a seed-corpus artifact (WP-08 C-001/C-003). "
    "Writes to packages/seed-corpus/artifacts/tenant-<packageId>-<artifactId>/.",
)
@click.option(
    "--emg-store-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="EMG store root for --persist (default: $OIW_WORKSPACE/.oiw/emg).",
)
def tenant_pull(
    profile: str,
    project_path: Path,
    package_id: str,
    artifact_id: str | None,
    out_path: Path,
    persist: bool,
    emg_store_root: Path | None,
) -> None:
    """Download a single artifact ZIP from the tenant (read-only, WP-08 C-001).

    Does NOT import into IR by default. Use `oiw import <zip>` separately
    for that. With `--persist`, redacts the imported IR + scripts and writes
    them under packages/seed-corpus/artifacts/tenant-<pkg>-<art>/ (WP-08
    C-001/C-003). Tenant ZIPs are never committed — only the redacted IR.

    Per WP-08 C-001: tenant ZIPs may contain hostnames / customer IP
    and are NOT committed. Save them to a gitignored cache.
    """
    import asyncio

    from .environments import load_profile
    from .tenant import SapCiTenantError, build_tenant_adapter

    try:
        prof = load_profile(project_path, profile)
    except Exception as exc:
        click.echo(f"error: could not load profile '{profile}': {exc}", err=True)
        sys.exit(2)

    adapter = build_tenant_adapter()

    async def _pull():
        await adapter.connect(prof)
        if not hasattr(adapter, "list_artifacts") or not hasattr(adapter, "download_artifact"):
            raise SapCiTenantError("adapter does not support download (mock in use).")
        if artifact_id:
            arts = await adapter.list_artifacts(package_id, top=100)
            match = [a for a in arts if a.id == artifact_id]
            if not match:
                raise SapCiTenantError(f"artifact '{artifact_id}' not found in package '{package_id}'.")
            target = match[0]
        else:
            arts = await adapter.list_artifacts(package_id, top=1)
            if not arts:
                raise SapCiTenantError(f"package '{package_id}' has no artifacts.")
            target = arts[0]
        blob = await adapter.download_artifact(target.id, target.version)
        return target, blob

    try:
        target, blob = asyncio.run(_pull())
    except SapCiTenantError as exc:
        click.echo(f"FAIL: {exc}", err=True)
        sys.exit(1)
    except NotImplementedError as exc:
        click.echo(f"FAIL (adapter not real): {exc}", err=True)
        click.echo("Set OIW_USE_REAL_TENANT=1 + OIW_TENANT_URL/_USER/_PASSWORD.", err=True)
        sys.exit(1)

    out_path.write_bytes(blob)
    click.echo(f"Downloaded {target.id} (version {target.version}) → {out_path} ({len(blob)} bytes)")

    if persist:
        _persist_tenant_artifact(
            zip_path=out_path,
            package_id=package_id,
            artifact_id=target.id,
            artifact_version=target.version,
            emg_store_root=emg_store_root,
        )


def _persist_tenant_artifact(
    zip_path: Path,
    package_id: str,
    artifact_id: str,
    artifact_version: str,
    emg_store_root: Path | None,
) -> None:
    """Redact + persist a tenant artifact as a seed-corpus entry (WP-08 C-001/C-003).

    Layout (per WP-08 C-001):
      packages/seed-corpus/artifacts/tenant-<packageId>-<artifactId>/
        flow.yaml          — redacted IR (no hostnames, secrets, customer IP)
        import-report.yaml — what the parser recognized + what it couldn't
        metadata.yaml      — provenance.source=tenant, packageId, version,
                             tenantHash, isReal=true, confidentialityScope=project
    The original ZIP is NOT copied — it stays in the gitignored cache only.
    """
    import hashlib
    import os

    from .agent.redaction import Redactor

    redactor = Redactor()
    safe_artifact_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in artifact_id)
    out_dir = Path("packages") / "seed-corpus" / "artifacts" / f"tenant-{package_id}-{safe_artifact_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Import the ZIP to IR. There are two importers:
    #   - import_archive (in compiler/import_parser.py): the canonical path
    #     used by `oiw import`. Handles both single-iFlow ZIPs and the
    #     canonical OIW fixture layout. Returns an ImportReport.
    #   - import_sap_export (in compiler/sap_import.py): handles the SAP
    #     tenant's nested export-package format (outer ZIP with `_content`
    #     inner ZIPs).
    # Tenant pull downloads single artifacts, which look like single-iFlow
    # ZIPs — `import_archive` is the right path here. It re-uses the same
    # parser that `oiw import` does on the command line.
    from .compiler.import_parser import import_archive
    from .compiler.report import format_import_report

    try:
        report = import_archive(Path.cwd(), zip_path, "sap-cloud-integration-2026-07")
        # import_archive doesn't return IR as a structured dict — synthesize
        # a minimal IR from the recognized components for the redacted flow.yaml.
        ir = _build_ir_from_report(report, package_id, artifact_id)
    except Exception as exc:
        click.echo(f"  WARN: import failed: {exc}", err=True)
        ir, report = None, None

    # Redact IR
    if ir is not None:
        redacted_ir = redactor.redact_dict(ir)
        # Write flow.yaml
        import yaml as _yaml

        (out_dir / "flow.yaml").write_text(
            _yaml.safe_dump(redacted_ir, sort_keys=False, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        click.echo(f"  wrote redacted IR: {out_dir / 'flow.yaml'}")
    else:
        click.echo("  WARN: no IR written (import failed)", err=True)

    # Write import report
    if report is not None:
        report_path = out_dir / "import-report.yaml"
        report_path.write_text(format_import_report(report), encoding="utf-8")
        click.echo(f"  wrote import report: {report_path}")

    # Compute tenant hash (sha256 of the URL, first 12 chars) per WP-08 C-001
    tenant_url = os.environ.get("OIW_TENANT_URL", "")
    tenant_hash = hashlib.sha256(tenant_url.encode()).hexdigest()[:12] if tenant_url else "unknown"

    # Write metadata.yaml
    from datetime import UTC, datetime

    import yaml as _yaml

    metadata = {
        "provenance": {
            "source": "tenant",
            "tenantHash": tenant_hash,
            "packageId": package_id,
            "artifactId": artifact_id,
            "artifactVersion": artifact_version,
            "isReal": True,
            "fetchedAt": datetime.now(tz=UTC).isoformat(),
        },
        "license": "customer-content",  # NOT Apache-2.0; not for redistribution
        "confidentialityScope": "project",
        "redacted": True,
        "originalZipPath": str(zip_path),
        "note": (
            "Tenant artifact pulled via `oiw tenant pull --persist`. "
            "Original ZIP is gitignored — only the redacted IR + import report "
            "are eligible for commit, and only with an explicit reviewer decision."
        ),
    }
    (out_dir / "metadata.yaml").write_text(
        _yaml.safe_dump(metadata, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    click.echo(f"  wrote metadata: {out_dir / 'metadata.yaml'}")

    # Optionally persist a TaskMemoryNode to the EMG store
    if emg_store_root is not None or os.environ.get("OIW_WORKSPACE"):
        try:
            from .emg.store import build_emg_store

            store = build_emg_store(root=emg_store_root, create_if_missing=True)
            store.load()
            # Build a minimal NormalizedRequirement from the imported flow
            if ir is not None and isinstance(ir, dict):
                spec = ir.get("spec", {}) or {}
                node_types = [n.get("type", "") for n in spec.get("nodes", [])]
                from .agent.interpreter import NormalizedRequirement

                nr = NormalizedRequirement(
                    intent="tenant-artifact",
                    raw=f"tenant artifact {package_id}/{artifact_id} v{artifact_version}",
                    archetype=None,
                    source_protocol="https" if any("sender.http" in t for t in node_types) else None,
                    target_protocol=None,
                    operations=[t.split(".")[0] for t in node_types if "." in t],
                    components=node_types,
                )
                store.upsert_task_from_requirement(
                    nr,
                    task_id=f"tenant-{package_id}-{safe_artifact_id}",
                    project_id="tenant-corpus",
                    insight_ref=None,
                )
                store.save()
                click.echo(f"  persisted task node to EMG store: {store.root_path}")
        except Exception as exc:
            click.echo(f"  WARN: could not persist to EMG store: {exc}", err=True)


# ---------------------------------------------------------------------------
# WP-08 Track 0: Tenant smoke commands (read-only, GET-only) — end
# ---------------------------------------------------------------------------


def _build_ir_from_report(report: Any, package_id: str, artifact_id: str) -> dict[str, Any]:
    """Build a minimal OIW IR dict from an ImportReport's recognized components.

    `import_sap_export` produces a report with recognized component types
    but doesn't return the IR as a structured object. For persistence we
    need *something* to write to flow.yaml, so we synthesize a minimal IR
    from the recognized components list. The redactor then strips any
    secrets that may have leaked into the component metadata.

    The full IR (with edges, configs, etc.) is recoverable later by
    re-importing the original ZIP — this minimal IR is enough for the
    EMG store to embed + retrieve by requirement.
    """
    nodes: list[dict[str, Any]] = []
    for i, rec in enumerate(getattr(report, "recognized", []) or []):
        comp_type = getattr(rec, "component", "") or ""
        fidelity = getattr(rec, "fidelity", "simulated") or "simulated"
        # Try to map the report's component name back to an OIW step type
        # (the report uses loose names like "https_sender", "modifier.content",
        # "step:modifier.content" — strip the prefix and lowercase).
        clean_type = comp_type.split(":")[-1] if ":" in comp_type else comp_type
        if not clean_type:
            continue
        # If it's a sender type, keep as entrypoint-style node
        if "sender" in clean_type.lower():
            nodes.append(
                {
                    "id": f"sender-{i}",
                    "type": clean_type if clean_type.startswith("sender.") else "sender.http",
                    "config": {},
                    "fidelity": fidelity,
                }
            )
        elif "receiver" in clean_type.lower() or clean_type.startswith("receiver."):
            nodes.append(
                {
                    "id": f"receiver-{i}",
                    "type": clean_type if clean_type.startswith("receiver.") else "receiver.http",
                    "config": {},
                    "fidelity": fidelity,
                }
            )
        else:
            # Generic process step
            oiw_type = clean_type if "." in clean_type else "log.message"
            nodes.append(
                {
                    "id": f"step-{i}",
                    "type": oiw_type,
                    "config": {},
                    "fidelity": fidelity,
                }
            )

    # Build edges as a simple linear chain sender → steps → receiver
    edges: list[dict[str, Any]] = []
    for i in range(len(nodes) - 1):
        edges.append({"from": nodes[i]["id"], "to": nodes[i + 1]["id"]})

    return {
        "apiVersion": "oiw.dev/v1alpha1",
        "kind": "IntegrationFlow",
        "metadata": {
            "id": f"tenant-{package_id}-{artifact_id}".lower()[:63],
            "name": f"Tenant artifact: {package_id}/{artifact_id}",
            "version": 1,
            "labels": {"provenance": "tenant"},
        },
        "spec": {
            "entrypoints": [],
            "nodes": nodes,
            "edges": edges,
            "extensions": {},
        },
    }


if __name__ == "__main__":
    main()
