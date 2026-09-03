"""B2 — Experiment Engine tests (roadmap handoff 2026-09-02, open thread 2).

Acceptance bar (roadmap §B2, verbatim):
    "Regression test: engine must re-derive the converter law from the
     conv1-conv10 corpus."

The conv1–conv10 campaign (2026-09-02, DEVELOPMENT_LOG "PHASE 3 COMPLETE")
was run BY HAND with exactly the discipline this engine automates:
single-variable variants of a green chain through the live oracle.
This suite reconstructs that corpus as rung records and asserts the
engine re-derives:

  - converter placement law (converter must be preceded by an RR —
    the RR-warmup the assembler inserts)
  - the runner's cool-down pacing + budgets (blood law: tenant wedges
    after ~10 rapid deploys/hour)
  - registry behavior: candidate -> record, corroboration merges
    evidence, manual blood laws are never touched by the engine
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "apps" / "cli"))

from oiw.experiment.engine import (  # noqa: E402
    VERDICT_GREEN,
    VERDICT_RED,
    LawCandidate,
    Rung,
    derive_laws,
    execution_order,
    generate_ladder,
    materialize_variant,
)
from oiw.experiment.registry import (  # noqa: E402
    LawRecord,
    LawRegistry,
    load_registry,
)
from oiw.experiment.runner import (  # noqa: E402
    ExperimentBudget,
    ExperimentRunner,
    verdict_from_calibration,
)
from oiw.project import IntegrationFlow, _load_flow  # noqa: E402

CONV_EXAMPLE = REPO_ROOT / "examples" / "oiw-conv-fwd"


def _green_cal() -> dict:
    return {
        "uploadedOk": True,
        "finalStatus": "STARTED",
        "messageSent": True,
        "httpResponseStatus": 200,
        "mplRows": [{"Status": "COMPLETED"}],
    }


def _red_cal_start() -> dict:
    return {"uploadedOk": True, "finalStatus": "ERROR", "messageSent": False}


def _red_cal_message() -> dict:
    # the conv1/conv2 failure mode: STARTs, message fails at the adapter
    return {
        "uploadedOk": True,
        "finalStatus": "STARTED",
        "messageSent": True,
        "httpResponseStatus": 500,
        "mplRows": [{"Status": "FAILED"}],
    }


class TestVerdictMapping:
    def test_full_success_is_green(self) -> None:
        assert verdict_from_calibration(_green_cal()) == VERDICT_GREEN

    def test_start_error_is_red(self) -> None:
        assert verdict_from_calibration(_red_cal_start()) == VERDICT_RED

    def test_message_failure_is_red(self) -> None:
        assert verdict_from_calibration(_red_cal_message()) == VERDICT_RED

    def test_upload_failure_is_red(self) -> None:
        assert verdict_from_calibration({"uploadedOk": False}) == VERDICT_RED

    def test_started_non_http_entrypoint_green(self) -> None:
        # PD listeners: no message leg exists; STARTED is the verdict
        cal = {
            "uploadedOk": True,
            "finalStatus": "STARTED",
            "messageSent": False,
            "artifactEntrypointIsHttp": False,
        }
        assert verdict_from_calibration(cal) == VERDICT_GREEN


class TestLadderGeneration:
    """Single-variable discipline + settled-law exclusions."""

    def _baseline(self) -> IntegrationFlow:
        return _load_flow(
            CONV_EXAMPLE / "flows" / "oiw-conv-fwd",
            CONV_EXAMPLE / "flows" / "oiw-conv-fwd" / "flow.yaml",
        )

    def test_every_rung_names_one_target(self) -> None:
        record = generate_ladder(self._baseline(), hypothesis="h")
        assert record.rungs, "ladder must not be empty"
        for r in record.rungs:
            assert r.target
            assert r.kind in ("drop", "move", "insert", "swap")

    def test_entrypoints_never_mutated(self) -> None:
        record = generate_ladder(self._baseline(), hypothesis="h")
        entry_ids = {"sender-main"}
        for r in record.rungs:
            assert r.target not in entry_ids

    def test_drop_rungs_cover_every_body_node(self) -> None:
        record = generate_ladder(self._baseline(), hypothesis="h")
        dropped = {r.target for r in record.rungs if r.kind == "drop"}
        assert dropped == {
            "rr-fetch",
            "step-1-converter-json-to-xml",
            "rr-post",
            "pd-terminator",
        }

    def test_max_rungs_respected(self) -> None:
        record = generate_ladder(self._baseline(), hypothesis="h", max_rungs=3)
        assert len(record.rungs) == 3

    def test_insert_rungs_use_provided_types_only(self) -> None:
        record = generate_ladder(
            self._baseline(),
            hypothesis="h",
            kinds=("insert",),
            insert_types=("converter.json-to-xml",),
            max_rungs=5,
        )
        assert all(r.kind == "insert" for r in record.rungs)
        assert all(r.detail["newType"] == "converter.json-to-xml" for r in record.rungs)


class TestMaterializeVariant:
    def _baseline(self) -> IntegrationFlow:
        return _load_flow(
            CONV_EXAMPLE / "flows" / "oiw-conv-fwd",
            CONV_EXAMPLE / "flows" / "oiw-conv-fwd" / "flow.yaml",
        )

    def test_drop_removes_and_splices(self) -> None:
        base = self._baseline()
        rung = Rung(rung_id="t1", kind="drop", target="rr-post")
        v = materialize_variant(base, rung)
        assert "rr-post" not in {n.id for n in v.nodes}
        # pred (converter) spliced to succ (pd-terminator)
        assert ("step-1-converter-json-to-xml", "pd-terminator") in {
            (e.from_, e.to) for e in v.edges
        }
        # baseline untouched
        assert "rr-post" in {n.id for n in base.nodes}

    def test_move_repositions(self) -> None:
        base = self._baseline()
        # move the converter to the FRONT of the body (position 0) —
        # this is exactly the conv1/conv2 mutation: converter before any RR
        rung = Rung(
            rung_id="t2", kind="move", target="step-1-converter-json-to-xml",
            detail={"toPosition": 0},
        )
        v = materialize_variant(base, rung)
        order = [nid for nid in execution_order(v) if nid != "sender-main"]
        assert order.index("step-1-converter-json-to-xml") == 0
        # and the chain re-links linearly through the new position
        assert (order[0], order[1]) == ("step-1-converter-json-to-xml", "rr-fetch")

    def test_insert_requires_proven_piece(self) -> None:
        base = self._baseline()
        rung = Rung(
            rung_id="t3", kind="insert", target="rr-fetch",
            detail={"newType": "not.a.piece"},
        )
        try:
            materialize_variant(base, rung)
            raise AssertionError("must refuse unproven insert types")
        except ValueError as exc:
            assert "not a proven piece" in str(exc)

    def test_insert_uses_piece_config(self) -> None:
        base = self._baseline()
        rung = Rung(
            rung_id="t4", kind="insert", target="rr-fetch",
            detail={"newType": "converter.xml-to-json", "after": "rr-fetch"},
        )
        pieces = {"converter.xml-to-json": {"someKey": "liveSafe"}}
        v = materialize_variant(base, rung, piece_provider=pieces)
        new = [n for n in v.nodes if n.type == "converter.xml-to-json"]
        assert len(new) == 1
        assert new[0].config == {"someKey": "liveSafe"}

    def test_swap_changes_type_only(self) -> None:
        base = self._baseline()
        rung = Rung(
            rung_id="t5", kind="swap", target="log-receiver-x",
            detail={"newType": "converter.xml-to-json"},
        )
        # target a real node:
        rung.target = "step-1-converter-json-to-xml"
        v = materialize_variant(base, rung, piece_provider={"converter.xml-to-json": {}})
        node = next(n for n in v.nodes if n.id == "step-1-converter-json-to-xml")
        assert node.type == "converter.xml-to-json"


class TestReDeriveConverterLaw:
    """THE acceptance test: engine re-derives the converter placement law.

    Corpus: the conv1–conv10 campaign (DEVELOPMENT_LOG 2026-09-02) run as
    a move-ladder over the conv10 green chain:

        sender -> RR(warmup) -> converter -> RR(POST) -> PD

    conv1/conv2 (RED): converter placed directly after the sender (no RR
    before it) — 'Member name not found' at the adapter.
    conv3/conv9/conv10 (GREEN): converter AFTER an RR works in every
    tested position.

    Derivation: moving the converter from position 0 (before any RR) is
    red; every position >= 1 (after an RR) is green. The engine must
    surface the placement law from exactly this verdict pattern.
    """

    def _baseline(self) -> IntegrationFlow:
        return _load_flow(
            CONV_EXAMPLE / "flows" / "oiw-conv-fwd",
            CONV_EXAMPLE / "flows" / "oiw-conv-fwd" / "flow.yaml",
        )

    def test_engine_rederives_converter_law(self) -> None:
        base = self._baseline()
        record = generate_ladder(
            base,
            hypothesis="converter placement (conv1-conv10 corpus)",
            kinds=("move",),
        )
        record.baseline_verdict = VERDICT_GREEN  # conv10 chain is green
        record.status = "complete"

        # Stamp the corpus verdicts: converter before any RR (position 0)
        # is RED (conv1/conv2); every later position is GREEN (conv3+).
        conv_node = "step-1-converter-json-to-xml"
        for r in record.rungs:
            if r.target != conv_node:
                # non-mutation rungs of other targets: not part of this
                # corpus — leave SKIPPED so laws only cite converter rungs
                continue
            to = int(r.detail["toPosition"])
            r.verdict = VERDICT_RED if to == 0 else VERDICT_GREEN
            r.evidence = {"targetType": "converter.json-to-xml"}
            if to == 0:
                r.evidence["mplStatuses"] = ["FAILED"]  # conv1/conv2 mode

        laws = derive_laws(record)

        # exactly one law cites the converter move rungs
        conv_laws = [law for law in laws if "converter" in law.statement or "converter" in law.scope]
        assert conv_laws, "engine must derive a law from the converter rungs"
        law = conv_laws[0]
        assert law.scope == "converter.json-to-xml"
        assert law.red_rungs, "the law must cite its red evidence"
        red_positions = set()
        for rid in law.red_rungs:
            r = record.rung(rid)
            assert r is not None
            red_positions.add(int(r.detail["toPosition"]))
        # the red positions are exactly the before-RR positions
        assert red_positions == {0}
        # and the law statement names the load-bearing placement
        assert "position" in law.statement or "placement" in law.statement

    def test_law_feeds_the_registry_with_evidence(self) -> None:
        base = self._baseline()
        record = generate_ladder(
            base, hypothesis="conv corpus", kinds=("move",)
        )
        record.baseline_verdict = VERDICT_GREEN
        record.status = "complete"
        conv_node = "step-1-converter-json-to-xml"
        for r in record.rungs:
            if r.target == conv_node:
                to = int(r.detail["toPosition"])
                r.verdict = VERDICT_RED if to == 0 else VERDICT_GREEN
                r.evidence = {"targetType": "converter.json-to-xml"}

        laws = derive_laws(record)
        reg = LawRegistry(Path("/tmp/oiw-test-laws.yaml"))
        recorded = reg.add_many(
            [LawRecord(
                law_id=law.law_id, statement=law.statement, scope=law.scope,
                kind=law.kind, origin=record.experiment_id,
                evidence={"greenRungs": law.green_rungs, "redRungs": law.red_rungs},
                confidence=law.confidence,
            ) for law in laws]
        )
        assert any(r.scope == "converter.json-to-xml" for r in recorded)
        conv = next(r for r in recorded if r.scope == "converter.json-to-xml")
        assert conv.evidence["redRungs"], "registry record must carry red evidence"
        assert conv.confidence >= 0.5

    def test_no_laws_from_red_baseline(self) -> None:
        base = self._baseline()
        record = generate_ladder(base, hypothesis="h", kinds=("drop",), max_rungs=2)
        record.baseline_verdict = VERDICT_RED  # baseline itself broken
        for r in record.rungs:
            r.verdict = VERDICT_RED
        assert derive_laws(record) == []


class TestRunnerBudgets:
    """Cool-down governor + rung budget + wall clock (blood law pacing)."""

    def test_budget_validation(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="max_rungs"):
            ExperimentBudget(max_rungs=0)
        with pytest.raises(ValueError, match="wall_clock"):
            ExperimentBudget(wall_clock_s=0)
        ExperimentBudget()  # defaults valid

    def test_rung_budget_skips_excess(self) -> None:
        base = _load_flow(
            CONV_EXAMPLE / "flows" / "oiw-conv-fwd",
            CONV_EXAMPLE / "flows" / "oiw-conv-fwd" / "flow.yaml",
        )
        record = generate_ladder(base, hypothesis="h", kinds=("drop",))
        calls: list[str] = []

        async def oracle(path, flow, *, artifact_id=None):
            calls.append(flow.id)
            return _green_cal()

        async def fast_sleep(_s):
            return None

        runner = ExperimentRunner(
            oracle,
            ExperimentBudget(max_rungs=1, cooldown_s=0, unattended=True),
            project_path=CONV_EXAMPLE,
            sleep=fast_sleep,
        )
        import asyncio

        record = asyncio.run(runner.run(record, base))
        assert record.status == "complete"
        assert record.baseline_verdict == VERDICT_GREEN
        executed = [r for r in record.rungs if r.verdict != "SKIPPED"]
        skipped = [r for r in record.rungs if r.verdict == "SKIPPED"]
        assert len(executed) == 1
        assert all("rung budget" in r.rationale for r in skipped)

    def test_cooldown_paces_deploys(self) -> None:
        base = _load_flow(
            CONV_EXAMPLE / "flows" / "oiw-conv-fwd",
            CONV_EXAMPLE / "flows" / "oiw-conv-fwd" / "flow.yaml",
        )
        record = generate_ladder(base, hypothesis="h", kinds=("drop",), max_rungs=2)
        sleeps: list[float] = []

        async def oracle(path, flow, *, artifact_id=None):
            return _green_cal()

        async def recording_sleep(s):
            if s > 0:
                sleeps.append(s)

        runner = ExperimentRunner(
            oracle,
            ExperimentBudget(max_rungs=5, cooldown_s=360.0, unattended=True),
            project_path=CONV_EXAMPLE,
            sleep=recording_sleep,
        )
        import asyncio

        asyncio.run(runner.run(record, base))
        # baseline + 4 drop rungs = 5 calls => 4 cooldown gaps measured
        # against a fast fake oracle -> each gap ~= cooldown_s
        assert sleeps, "cool-down governor must pace deploys"
        assert all(s > 300 for s in sleeps)


class TestRegistryBehavior:
    def test_record_roundtrip(self, tmp_path: Path) -> None:
        reg = LawRegistry(tmp_path / "tenant-laws.yaml")
        rec = LawRecord(
            law_id="law-1",
            statement="s",
            scope="converter.json-to-xml",
            kind="move",
            origin="exp-1",
        )
        reg.add(rec)
        reg.save()
        reg2 = LawRegistry(tmp_path / "tenant-laws.yaml").load()
        assert reg2.get("law-1") is not None
        assert reg2.get("law-1").origin == "exp-1"

    def test_corroboration_merges_evidence(self) -> None:
        reg = LawRegistry(Path("/tmp/oiw-test-laws2.yaml"))
        first = LawRecord(
            law_id="law-a",
            statement="placement law",
            scope="converter.json-to-xml",
            kind="move",
            origin="exp-1",
            evidence={"greenRungs": ["g1"], "redRungs": ["r1"]},
            confidence=0.5,
        )
        reg.add(first)
        cand = LawCandidate(
            law_id="law-b",
            statement="placement law again",
            scope="converter.json-to-xml",
            kind="move",
            green_rungs=["g2"],
            red_rungs=["r2"],
        )
        existing = reg.corroboration_for(cand)
        assert existing is not None and existing.law_id == "law-a"
        reg.merge_evidence(existing, cand)
        assert "r2" in existing.evidence["redRungs"]
        assert existing.confidence > 0.5

    def test_manual_laws_not_corroborated_by_engine(self) -> None:
        reg = LawRegistry(Path("/tmp/oiw-test-laws3.yaml"))
        manual = LawRecord(
            law_id="law-manual-1",
            statement="blood law",
            scope="flow.topology",
            kind="drop",
            origin="manual",
            source="manual",
            status="ratified",
        )
        reg.add(manual)
        cand = LawCandidate(
            law_id="law-x",
            statement="same shape",
            scope="flow.topology",
            kind="drop",
        )
        assert reg.corroboration_for(cand) is None

    def test_load_registry_resolves_workspace(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("OIW_WORKSPACE", str(tmp_path))
        reg = load_registry()
        assert reg.path == tmp_path / ".oiw" / "tenant-laws.yaml"


class TestRecordPersistence:
    def test_record_roundtrip(self, tmp_path: Path) -> None:
        from oiw.experiment.runner import load_record, save_record

        record = generate_ladder(
            _load_flow(
                CONV_EXAMPLE / "flows" / "oiw-conv-fwd",
                CONV_EXAMPLE / "flows" / "oiw-conv-fwd" / "flow.yaml",
            ),
            hypothesis="persist me",
        )
        record.baseline_verdict = VERDICT_GREEN
        record.status = "complete"
        record.rungs[0].verdict = VERDICT_RED
        record.rungs[0].evidence = {"targetType": "receiver.http"}

        path = save_record(record, tmp_path / "experiments")
        loaded = load_record(path)
        assert loaded.hypothesis == "persist me"
        assert loaded.baseline_verdict == VERDICT_GREEN
        assert loaded.rungs[0].verdict == VERDICT_RED
        assert loaded.rungs[0].evidence == {"targetType": "receiver.http"}
