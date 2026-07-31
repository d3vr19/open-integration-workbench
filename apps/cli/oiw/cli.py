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
def validate(project_path: Path, strict: bool) -> None:
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
def test(
    project_path: Path, all_tests: bool, flow_id: str | None, test_name: str | None, junit_path: Path | None
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


if __name__ == "__main__":
    main()
