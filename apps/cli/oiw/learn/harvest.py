"""Pattern-book harvester (Phase 1) — self-discovery of CPI shapes.

The tenant's own package catalog IS the shape documentation: every
UI-authored iFlow in every Discover-Package carries adapter property sets
proven by real authoring. This harvester crawls packages (read-only GETs),
parses every .iflw, clusters messageFlow adapter shapes by
(ComponentType, direction), censuses step activities, and emits:

    packages/pattern-book/census.yaml        — frequency report
    packages/pattern-book/shapes/<Key>.yaml  — canonical templates

Exporter coverage gaps fall out of the census: shapes with high frequency
but no exporter mapping are the grammar backlog. Shapes only ENTER the
exporter after live oracle validation — discovery nominates, oracle proves.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

B = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"
IFL = "{http:///com.sap.ifl.model/Ifl.xsd}"

# Volatile props excluded from signatures (per-flow values, not shape).
VOLATILE_KEYS = {
    "address",
    "urlPath",
    "httpAddressWithoutQuery",
    "httpAddressQuery",
    "system",
    "Description",
    "variable",
    "script",
    "wrapContent",
    "cmdVariantUri",
}

ACTIVITY_TAGS = ("startEvent", "endEvent", "serviceTask", "callActivity", "task")


@dataclass
class ShapeObservation:
    component_type: str
    direction: str
    name: str  # adapter display name (HTTP / HTTPS / ProcessDirect / ...)
    props: dict[str, str] = field(default_factory=dict)
    source_artifacts: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.component_type or 'UNKNOWN'}-{self.direction}".replace(" ", "_")


def _props(el: ET.Element) -> dict[str, str]:
    ee = el.find(f"{B}extensionElements")
    if ee is None:
        return {}
    return {p.findtext("key") or "": p.findtext("value") or "" for p in ee.findall(f"{IFL}property")}


def parse_iflw_shapes(xml: str) -> tuple[list[ShapeObservation], dict[str, int]]:
    """Extract adapter shapes + activity-type counts from one .iflw."""
    shapes: list[ShapeObservation] = []
    activities: dict[str, int] = {}
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return shapes, activities
    collab = root.find(f"{B}collaboration")
    if collab is not None:
        for mf in collab.findall(f"{B}messageFlow"):
            p = _props(mf)
            ct = p.get("ComponentType", "")
            if not ct:
                continue
            shapes.append(
                ShapeObservation(
                    component_type=ct,
                    direction=p.get("direction", "?"),
                    name=p.get("Name", ct),
                    props={k: v for k, v in p.items() if k not in VOLATILE_KEYS},
                )
            )
    process = root.find(f"{B}process")
    if process is not None:
        for el in process.iter():
            tag = el.tag.split("}")[-1]
            if tag in ACTIVITY_TAGS:
                p = _props(el)
                at = p.get("activityType")
                if at:
                    activities[at] = activities.get(at, 0) + 1
    return shapes, activities


def cluster(observations: list[ShapeObservation]) -> list[ShapeObservation]:
    """Collapse observations with identical signature; track provenance."""
    out: dict[tuple, ShapeObservation] = {}
    for o in observations:
        sig = tuple(sorted(o.props.items()))
        k = (o.key, o.name, sig)
        if k in out:
            out[k].source_artifacts.extend(o.source_artifacts)
        else:
            o.source_artifacts = list(o.source_artifacts)
            out[k] = o
    return sorted(out.values(), key=lambda s: -len(s.source_artifacts))


async def harvest(
    adapter,
    *,
    max_artifacts: int = 300,
    per_package_cap: int = 12,
    progress=None,
) -> tuple[dict[str, ShapeObservation], dict[str, int], int]:
    """Crawl all visible packages. Returns (shapes, activities, scanned)."""
    packages = await adapter.list_packages(top=200)
    all_obs: list[ShapeObservation] = []
    activities: dict[str, int] = {}
    scanned = 0
    budget = max_artifacts

    # Round-robin across packages for adapter diversity.
    queues: dict[str, list] = {}
    for pkg in packages:
        try:
            queues[pkg.id] = await adapter.list_artifacts(pkg.id, top=50)
        except Exception:
            continue

    while budget > 0 and any(q for q in queues.values()):
        for pkg_id in list(queues):
            q = queues.get(pkg_id) or []
            if not q or budget <= 0:
                continue
            art = q.pop(0)
            budget -= 1
            scanned += 1
            if progress:
                progress(scanned, pkg_id, art.id)
            try:
                blob = await adapter.download_artifact(art.id, art.version)
            except Exception:
                continue
            zf = zipfile.ZipFile(io.BytesIO(blob))
            for name in zf.namelist():
                if not name.endswith(".iflw"):
                    continue
                xml = zf.read(name).decode("utf-8", errors="replace")
                shapes, acts = parse_iflw_shapes(xml)
                for s in shapes:
                    s.source_artifacts = [f"{pkg_id}/{art.id}"]
                    all_obs.append(s)
                for a, n in acts.items():
                    activities[a] = activities.get(a, 0) + n
                break  # one .iflw per artifact is the norm
    clustered = cluster(all_obs)
    by_key: dict[str, ShapeObservation] = {}
    for c in clustered:
        key = f"{c.key}-{c.name}"
        if key in by_key:
            by_key[key].source_artifacts.extend(c.source_artifacts)
        else:
            by_key[key] = c
    return by_key, activities, scanned


def write_pattern_book(
    out_dir: Path,
    shapes: dict[str, ShapeObservation],
    activities: dict[str, int],
    scanned: int,
    known_exporter_types: set[str],
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    shapes_dir = out_dir / "shapes"
    shapes_dir.mkdir(exist_ok=True)

    census = {
        "harvestedAt": __import__("datetime").datetime.now().isoformat(),
        "artifactsScanned": scanned,
        "distinctShapes": len(shapes),
        "activityCounts": dict(sorted(activities.items(), key=lambda kv: -kv[1])),
        "shapes": [],
    }
    safe = re.compile(r"[^A-Za-z0-9_-]")
    for key, s in sorted(shapes.items(), key=lambda kv: -len(kv[1].source_artifacts)):
        covered = any(s.component_type.lower().startswith(t.lower()) for t in known_exporter_types)
        entry = {
            "shape": key,
            "componentType": s.component_type,
            "direction": s.direction,
            "name": s.name,
            "observedIn": len(set(s.source_artifacts)),
            "exporterCovered": covered,
            "examples": sorted(set(s.source_artifacts))[:5],
        }
        census["shapes"].append(entry)
        slug = safe.sub("_", key)[:80]
        (shapes_dir / f"{slug}.yaml").write_text(
            yaml.safe_dump({"props": s.props, **entry}, sort_keys=False),
            encoding="utf-8",
        )

    out = out_dir / "census.yaml"
    out.write_text(yaml.safe_dump(census, sort_keys=False), encoding="utf-8")
    return out


EXPORTER_COVERED_TYPES = {"HTTP", "HTTPS", "PROCESSDIRECT"}
