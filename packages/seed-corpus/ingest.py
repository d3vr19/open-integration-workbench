"""Batch artifact ingestion pipeline (WP-06 Task A-002).

Spec ref: §15.14 (Seed Corpus).

Ingests approved artifacts into the OIW IR format:
  1. Load the flow.yaml from the source
  2. Validate against the IR schema
  3. Copy IR + resources + tests to packages/seed-corpus/artifacts/{id}/
  4. Generate metadata.yaml with source, license, audit status

For OIW examples (already in IR format), this is a copy + validate step.
For synthetic artifacts (B-007), the flow.yaml is created by the generator.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))


@dataclass
class IngestResult:
    """Result of ingesting a single artifact."""

    artifact_id: str
    source: str
    ingested: bool = False
    flow_id: str | None = None
    node_count: int = 0
    resource_count: int = 0
    test_count: int = 0
    errors: list[str] = field(default_factory=list)


def ingest_artifact(
    source_dir: Path | str,
    artifact_id: str,
    output_dir: Path | str,
    source: str = "oiw-example",
    license_spdx: str = "Apache-2.0",
) -> IngestResult:
    """Ingest a single artifact from source_dir to output_dir/{artifact_id}/.

    Args:
        source_dir: Directory containing flow.yaml + resources/ + tests/.
        artifact_id: ID for the artifact in the seed corpus.
        output_dir: Base output directory (artifacts go to {output_dir}/{artifact_id}/).
        source: Source identifier.
        license_spdx: SPDX license identifier.

    Returns:
        IngestResult with status + counts.
    """
    source_dir = Path(source_dir)
    out_dir = Path(output_dir) / artifact_id
    result = IngestResult(artifact_id=artifact_id, source=source)

    # Find flow.yaml
    flow_yaml = source_dir / "flow.yaml"
    if not flow_yaml.is_file():
        result.errors.append("flow.yaml not found")
        return result

    # Load + validate flow.yaml
    try:
        ir = yaml.safe_load(flow_yaml.read_text(encoding="utf-8"))
        flow_id = ir.get("metadata", {}).get("id", artifact_id)
        result.flow_id = flow_id
        result.node_count = len(ir.get("spec", {}).get("nodes", []))
    except Exception as exc:
        result.errors.append(f"invalid flow.yaml: {exc}")
        return result

    # Create output directory
    out_dir.mkdir(parents=True, exist_ok=True)

    # Copy flow.yaml
    shutil.copy2(flow_yaml, out_dir / "flow.yaml")

    # Copy diagram.json if exists
    diagram = source_dir / "diagram.json"
    if diagram.is_file():
        shutil.copy2(diagram, out_dir / "diagram.json")

    # Copy resources/
    resources_dir = source_dir / "resources"
    if resources_dir.is_dir():
        dest_resources = out_dir / "resources"
        dest_resources.mkdir(exist_ok=True)
        for item in resources_dir.rglob("*"):
            if item.is_file():
                rel = item.relative_to(resources_dir)
                dest = dest_resources / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
                result.resource_count += 1

    # Copy tests/
    tests_dir = source_dir / "tests"
    if tests_dir.is_dir():
        dest_tests = out_dir / "tests"
        dest_tests.mkdir(exist_ok=True)
        for item in tests_dir.rglob("*"):
            if item.is_file():
                rel = item.relative_to(tests_dir)
                dest = dest_tests / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
                result.test_count += 1

    # Generate metadata.yaml
    metadata = {
        "artifactId": artifact_id,
        "source": source,
        "license": license_spdx,
        "ingestedAt": datetime.now().isoformat(),
        "flowId": flow_id,
        "nodeCount": result.node_count,
        "resourceCount": result.resource_count,
        "testCount": result.test_count,
    }
    (out_dir / "metadata.yaml").write_text(
        yaml.safe_dump(
            metadata, sort_keys=False, default_flow_style=False, allow_unicode=True
        ),
        encoding="utf-8",
    )

    result.ingested = True
    return result


def ingest_oiw_examples(output_dir: Path | str | None = None) -> list[IngestResult]:
    """Ingest all OIW example projects into the seed corpus.

    Returns list of IngestResult for each example.
    """
    artifacts_dir = output_dir or (Path(__file__).parent / "artifacts")
    results = []

    for example_name in ["order-to-s4", "sftp-order-drop"]:
        example_root = REPO_ROOT / "examples" / example_name
        if not example_root.is_dir():
            continue

        # Find all flows in the example
        flows_dir = example_root / "flows"
        if not flows_dir.is_dir():
            continue

        for flow_dir in sorted(flows_dir.iterdir()):
            if not flow_dir.is_dir() or not (flow_dir / "flow.yaml").is_file():
                continue
            flow_id = flow_dir.name
            artifact_id = f"{example_name}-{flow_id}"
            result = ingest_artifact(
                source_dir=flow_dir,
                artifact_id=artifact_id,
                output_dir=artifacts_dir,
                source=f"oiw-example-{example_name}",
            )
            results.append(result)

    return results


def get_all_artifact_dirs(corpus_dir: Path | str | None = None) -> list[Path]:
    """List all ingested artifact directories."""
    artifacts_dir = corpus_dir or (Path(__file__).parent / "artifacts")
    if not artifacts_dir.is_dir():
        return []
    return sorted(
        d for d in artifacts_dir.iterdir() if d.is_dir() and (d / "flow.yaml").is_file()
    )


__all__ = [
    "IngestResult",
    "get_all_artifact_dirs",
    "ingest_artifact",
    "ingest_oiw_examples",
]
