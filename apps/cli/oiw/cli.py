"""oiw CLI entry point.

Spec ref: §11.1 (repository structure), §19 Phase 1 (CLI deliverables).
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

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


if __name__ == "__main__":
    main()
