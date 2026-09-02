"""Phase C — closed LLM-free learning loop tests (p5-p6-plan.md §5C).

Covers:
  - C-1 promote_oracle_outcome: full-success oracle runs become durable
    PROJECT_APPROVED insights + task nodes with tenant-oracle provenance;
    partial failures do NOT promote.
  - C-2 file_oracle_failure / file_parity_miss: failures become triage
    candidates with suggested triage classes; nothing auto-promotes.
  - C-3 harvest_schedule: TTL gate, census back-compat, save/load.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from oiw.emg.promotion import MemoryPromotionState
from oiw.emg.store import JsonlEmgStore
from oiw.learn.harvest_schedule import (
    DEFAULT_TTL_DAYS,
    HarvestSchedule,
    load_schedule,
    save_schedule,
)
from oiw.learn.loop import (
    ORACLE_PROVENANCE_SOURCE,
    file_oracle_failure,
    file_parity_miss,
    oracle_insight_from_flow,
    record_oracle_run,
)
from oiw.tenant.calibrate import CalibrationReport

REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLE = REPO_ROOT / "examples" / "held-out-order-async"


def _success_report(artifact: str = "open_mateo_test") -> CalibrationReport:
    rep = CalibrationReport(package_id="AdaequareGST", artifact_id=artifact)
    rep.uploaded_ok = True
    rep.deploy_accepted = True
    rep.final_status = "STARTED"
    rep.message_sent = True
    rep.http_response_status = 200
    rep.mpl_rows = [{"MessageGuid": "g1", "Status": "COMPLETED"}]
    rep.started_at = datetime.now(tz=UTC).isoformat()
    return rep


def _failed_report(artifact: str = "open_mateo_test") -> CalibrationReport:
    rep = CalibrationReport(package_id="AdaequareGST", artifact_id=artifact)
    rep.uploaded_ok = True
    rep.deploy_accepted = True
    rep.final_status = "ERROR"
    rep.error_detail = "runtime start failed"
    rep.started_at = datetime.now(tz=UTC).isoformat()
    return rep


@pytest.fixture()
def project_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "prj"
    shutil.copytree(EXAMPLE, dest)
    return dest


@pytest.fixture()
def store(tmp_path: Path) -> JsonlEmgStore:
    s = JsonlEmgStore(root=tmp_path / "emg", create_if_missing=True)
    s.load()
    return s


class TestPromoteOracleOutcome:
    """C-1: successful oracle runs promote real insights."""

    def test_full_success_promotes_project_approved_insight(
        self, project_copy: Path, store: JsonlEmgStore
    ) -> None:
        from oiw.learn.loop import promote_oracle_outcome

        outcome = promote_oracle_outcome(_success_report(), project_copy, durable_store=store)
        assert outcome.promoted
        assert outcome.insight_id is not None

        records = store.list_insights(state=MemoryPromotionState.PROJECT_APPROVED)
        assert len(records) == 1
        rec = records[0]
        assert rec.insight is not None
        assert rec.insight.provenance is not None
        assert rec.insight.provenance.match_stage == "oracle"
        assert getattr(rec.insight, "oracle_detail", {}).get("source") == (ORACLE_PROVENANCE_SOURCE)
        # The successful workflow mirrors the flow's actual node chain.
        workflow_types = [n["action"][2] for n in rec.insight.successful_workflow]
        assert "sender.http" in workflow_types
        assert "log.message" in workflow_types
        assert "receiver.http" in workflow_types

    def test_promoted_insight_survives_restart_and_retrieves(
        self, project_copy: Path, tmp_path: Path
    ) -> None:
        from oiw.agent.interpreter import interpret_requirement_fallback
        from oiw.emg.retrieval import EMGRetriever
        from oiw.learn.loop import promote_oracle_outcome

        store = JsonlEmgStore(root=tmp_path / "emg", create_if_missing=True)
        store.load()
        promote_oracle_outcome(_success_report(), project_copy, durable_store=store)

        # Process restart: a fresh store instance over the same root.
        store2 = JsonlEmgStore(root=tmp_path / "emg")
        store2.load()
        retriever = EMGRetriever(
            store=store2._insight_store,
            task_store=store2._task_store,
            edge_store=store2._edge_store,
            embedder=store2._embedder,
        )
        req = interpret_requirement_fallback(
            "Create a flow that receives an order via HTTPS, logs it, " "and forwards it to an order API"
        )
        result = retriever.retrieve(req, project_id="held-out-order-async")
        assert result.found
        assert result.insight is not None
        assert result.confidence >= 0.3

    def test_started_without_message_does_not_promote(self, project_copy: Path, store: JsonlEmgStore) -> None:
        from oiw.learn.loop import promote_oracle_outcome

        rep = _success_report()
        rep.message_sent = False  # bare START, not full success
        outcome = promote_oracle_outcome(rep, project_copy, durable_store=store)
        assert not outcome.promoted
        assert store.list_insights() == []

    def test_mpl_failure_does_not_promote(self, project_copy: Path, store: JsonlEmgStore) -> None:
        from oiw.learn.loop import promote_oracle_outcome

        rep = _success_report()
        rep.mpl_rows = [
            {"Status": "COMPLETED"},
            {"Status": "FAILED"},
        ]
        outcome = promote_oracle_outcome(rep, project_copy, durable_store=store)
        assert not outcome.promoted


class TestFileFailures:
    """C-2: failures become triage candidates, never promotions."""

    def test_oracle_failure_files_candidate_with_triage(self, tmp_path: Path) -> None:
        outcome = file_oracle_failure(_failed_report(), tmp_path / "cands")
        assert outcome.candidate_path is not None
        assert outcome.candidate_path.is_file()
        data = yaml.safe_load(outcome.candidate_path.read_text())
        cand = data["candidate"]
        assert cand["kind"] == "oracle-failure"
        assert cand["provenance"]["source"] == ORACLE_PROVENANCE_SOURCE
        assert cand["verdict"]["diagnostic"] == "ORACLE-RUNTIME-START-FAILED"
        assert cand["suggestedTriage"] == "exporter-fix"
        assert cand["provenance"]["isReal"] is True

    def test_message_failure_suggests_executor_test(self, tmp_path: Path) -> None:
        rep = _success_report()
        rep.mpl_rows = [{"Status": "FAILED"}]
        outcome = file_oracle_failure(rep, tmp_path / "cands")
        data = yaml.safe_load(outcome.candidate_path.read_text())
        assert data["candidate"]["suggestedTriage"] == "executor-test"

    def test_parity_miss_files_candidate(self, tmp_path: Path) -> None:
        row = {
            "name": "held-out-order-async",
            "project": "examples/held-out-order-async",
            "localStatus": "PASS",
            "oracle": {"finalStatus": "ERROR", "messageSent": True},
            "details": "local=PASS vs oracle=ERROR",
            "oracleReportAgeHours": 1.0,
        }
        outcome = file_parity_miss(row, tmp_path / "cands")
        data = yaml.safe_load(outcome.candidate_path.read_text())
        cand = data["candidate"]
        assert cand["kind"] == "parity-mismatch"
        assert cand["suggestedTriage"] == "exporter-fix"
        assert cand["provenance"]["case"] == "held-out-order-async"

    def test_parity_local_fail_oracle_started_suggests_executor_test(self, tmp_path: Path) -> None:
        row = {
            "name": "some-case",
            "localStatus": "FAIL",
            "oracle": {"finalStatus": "STARTED"},
        }
        outcome = file_parity_miss(row, tmp_path / "cands")
        data = yaml.safe_load(outcome.candidate_path.read_text())
        assert data["candidate"]["suggestedTriage"] == "executor-test"


class TestRecordOracleRun:
    """The router: one call, promote-or-file semantics."""

    def test_success_routes_to_promotion(
        self, project_copy: Path, store: JsonlEmgStore, tmp_path: Path
    ) -> None:
        outcome = record_oracle_run(
            _success_report(),
            project_copy,
            durable_store=store,
            candidates_dir=tmp_path / "cands",
        )
        assert outcome.promoted
        assert outcome.candidate_id is None
        assert not list((tmp_path / "cands").glob("*.yaml")) if (tmp_path / "cands").exists() else True

    def test_failure_routes_to_candidate(
        self, project_copy: Path, store: JsonlEmgStore, tmp_path: Path
    ) -> None:
        outcome = record_oracle_run(
            _failed_report(),
            project_copy,
            durable_store=store,
            candidates_dir=tmp_path / "cands",
        )
        assert not outcome.promoted
        assert outcome.candidate_path is not None
        assert outcome.candidate_path.is_file()
        assert store.list_insights() == []

    def test_incomplete_run_is_neither(
        self, project_copy: Path, store: JsonlEmgStore, tmp_path: Path
    ) -> None:
        rep = _success_report()
        rep.final_status = "UNKNOWN"  # poll never terminal + message not sent
        rep.message_sent = False
        outcome = record_oracle_run(rep, project_copy, durable_store=store, candidates_dir=tmp_path / "cands")
        assert not outcome.promoted
        assert outcome.candidate_id is None


class TestOracleInsightShape:
    def test_insight_workflow_is_flow_shape(self, project_copy: Path) -> None:
        from oiw.project import Project

        project = Project.load(project_copy)
        flow = project.flows[0]
        insight = oracle_insight_from_flow(flow, _success_report())
        types = [n["action"][2] for n in insight.successful_workflow]
        # Entrypoint first (BFS from entrypoints), then chain, then
        # terminator (live topology law: HTTP receivers sit mid-chain as
        # Request-Reply; PD terminates).
        assert types[0] == "sender.http"
        assert "receiver.http" in types
        assert types[-1].startswith("receiver.")
        assert all(isinstance(n["action"], tuple) for n in insight.successful_workflow)


class TestHarvestSchedule:
    """C-3: TTL-gated harvest schedule."""

    def test_never_harvested_is_due(self, tmp_path: Path) -> None:
        s = HarvestSchedule()
        assert s.is_due()

    def test_recent_harvest_not_due(self) -> None:
        s = HarvestSchedule(last_harvest_at=datetime.now(tz=UTC))
        assert not s.is_due()
        assert s.next_due_at() is not None

    def test_stale_harvest_due_again(self) -> None:
        s = HarvestSchedule(last_harvest_at=datetime.now(tz=UTC) - timedelta(days=DEFAULT_TTL_DAYS + 1))
        assert s.is_due()

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        s = HarvestSchedule(
            last_harvest_at=datetime.now(tz=UTC),
            artifacts_scanned=300,
            distinct_shapes=59,
            ttl_days=3.0,
        )
        save_schedule(tmp_path, s)
        loaded = load_schedule(tmp_path)
        assert loaded.artifacts_scanned == 300
        assert loaded.distinct_shapes == 59
        assert loaded.ttl_days == 3.0
        assert not loaded.is_due()

    def test_census_backcompat(self, tmp_path: Path) -> None:
        # One-shot harvest era: only census.yaml exists, no sidecar.
        (tmp_path / "census.yaml").write_text(
            yaml.safe_dump(
                {
                    "harvestedAt": "2026-08-26T10:00:00",
                    "artifactsScanned": 300,
                    "distinctShapes": 59,
                }
            )
        )
        s = load_schedule(tmp_path)
        assert s.last_harvest_at is not None
        assert s.artifacts_scanned == 300
        assert s.distinct_shapes == 59

    def test_malformed_state_degrades_to_never(self, tmp_path: Path) -> None:
        (tmp_path / "harvest-state.yaml").write_text("schedule:\n  lastHarvestAt: 'not-a-date'\n")
        s = load_schedule(tmp_path)
        assert s.last_harvest_at is None
        assert s.is_due()
