"""Tests for trajectory recorder, normalization, and redaction (WP-04 Task 4).

Covers spec §15.2 (trajectory shape), §15.4 (action normalization),
§15.5 (observation normalization), §15.17 (redaction).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from oiw.agent.normalization import (
    arguments_digest,
    normalize_action,
    normalize_observation,
)
from oiw.agent.redaction import Redactor
from oiw.agent.trajectory import (
    TrajectoryRecorder,
)

# ---------------------------------------------------------------------------
# Normalization (spec §15.4, §15.5)
# ---------------------------------------------------------------------------


class TestNormalizeAction:
    def test_single_addnode_validator(self) -> None:
        args = {
            "projectId": "p",
            "flowId": "f",
            "baseRevision": "abc",
            "operations": [
                {"op": "addNode", "node": {"id": "validate-input", "type": "validator.json-schema"}}
            ],
        }
        result = normalize_action("flow.patch", args)
        assert result[0] == "flow.patch"
        assert result[1] == "addNode"
        assert result[2] == "validator.json-schema"
        # semantic target should be a non-empty string
        assert isinstance(result[3], str)

    def test_multi_op_flow_patch(self) -> None:
        args = {
            "operations": [
                {"op": "addNode", "node": {"id": "a", "type": "log.message"}},
                {"op": "addNode", "node": {"id": "b", "type": "log.message"}},
            ]
        }
        result = normalize_action("flow.patch", args)
        assert result == ("flow.patch", "multi-op", "2-operations", "", "")

    def test_resource_write_add(self) -> None:
        args = {
            "projectId": "p",
            "path": "flows/order-to-s4/resources/schemas/order.schema.json",
            "content": "{}",
        }
        result = normalize_action("resource.write", args)
        assert result[0] == "resource.write"
        assert result[1] == "add-resource"
        assert result[2] == "schema.json"
        # semantic ref should anonymize the flow ID
        assert "<flow>" in result[3]

    def test_test_create(self) -> None:
        args = {"projectId": "p", "flowId": "order-to-s4", "testName": "agent-test"}
        result = normalize_action("test.create", args)
        assert result == ("test.create", "add-test", "flow-test", "order-to-s4", "")

    def test_unknown_tool_passthrough(self) -> None:
        result = normalize_action("some.unknown.tool", {"foo": "bar"})
        assert result == ("some.unknown.tool", "invoke", "", "", "")

    def test_arguments_digest_stable(self) -> None:
        args = {"b": 2, "a": 1}
        d1 = arguments_digest(args)
        d2 = arguments_digest({"a": 1, "b": 2})  # different insertion order
        assert d1 == d2
        # SHA-256 hex
        assert len(d1) == 64
        assert all(c in "0123456789abcdef" for c in d1)

    def test_arguments_digest_differs_for_different_args(self) -> None:
        assert arguments_digest({"a": 1}) != arguments_digest({"a": 2})


class TestNormalizeObservation:
    def test_diagnostic_normalization(self) -> None:
        diag = {
            "category": "validation",
            "code": "OIW-E001",
            "componentRole": "validator-node",
            "targetProfile": "sap-ci-2026-07",
        }
        result = normalize_observation(diag)
        assert result == ("validation", "OIW-E001", "validator-node", "sap-ci-2026-07")

    def test_missing_fields_default(self) -> None:
        result = normalize_observation({})
        assert result == ("unknown", "NONE", "", "")


# ---------------------------------------------------------------------------
# Redaction (spec §15.17)
# ---------------------------------------------------------------------------


class TestRedactor:
    def test_redacts_bearer_token(self) -> None:
        r = Redactor()
        assert "[REDACTED_BEARER]" in r.redact("Authorization: Bearer abc.def.ghi")

    def test_redacts_password(self) -> None:
        r = Redactor()
        out = r.redact('password="supersecret123"')
        assert "supersecret123" not in out
        assert "[REDACTED]" in out

    def test_redacts_client_secret(self) -> None:
        r = Redactor()
        out = r.redact("clientSecret: 'oauth-secret-xyz'")
        assert "oauth-secret-xyz" not in out

    def test_redacts_private_key(self) -> None:
        r = Redactor()
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        out = r.redact(text)
        assert "[REDACTED_KEY]" in out
        assert "MIIEpAIBAAKCAQEA" not in out

    def test_redacts_sap_url(self) -> None:
        r = Redactor()
        out = r.redact("POST https://mytenant.sap.com/api/v1/orders")
        assert "[REDACTED_SAP_URL]" in out
        assert "mytenant.sap.com" not in out

    def test_redact_dict_recursive(self) -> None:
        r = Redactor()
        d = {
            "header": "Authorization: Bearer xyz",
            "body": {"password": "pw", "other": "ok"},
            "list": ["Bearer abc.def", "plain"],
        }
        out = r.redact_dict(d)
        assert "[REDACTED_BEARER]" in out["header"]
        assert "pw" not in str(out["body"])
        assert out["body"]["other"] == "ok"
        assert "[REDACTED_BEARER]" in out["list"][0]
        assert out["list"][1] == "plain"

    def test_redact_preserves_non_string_values(self) -> None:
        r = Redactor()
        d = {"count": 42, "ok": True, "items": [1, 2, 3]}
        out = r.redact_dict(d)
        assert out == d


# ---------------------------------------------------------------------------
# Trajectory recorder (spec §15.2)
# ---------------------------------------------------------------------------


class TestTrajectoryRecorder:
    def test_recorder_initial_state(self, tmp_path: Path) -> None:
        rec = TrajectoryRecorder(
            project_id="p1",
            task_id="t1",
            base_revision="abc123",
            persist_dir=tmp_path,
        )
        assert rec.trajectory_id.startswith("traj-")
        assert rec.trajectory.metadata.projectId == "p1"
        assert rec.trajectory.metadata.baseRevision == "abc123"
        assert rec.trajectory.spec.outcome.status == "in_progress"
        assert rec.trajectory.spec.steps == []

    def test_set_query_redacts_raw(self, tmp_path: Path) -> None:
        rec = TrajectoryRecorder("p", "t", "rev", persist_dir=tmp_path)
        rec.set_query(
            raw="My password=hunter2 and Bearer abc.def",
            normalized={"intent": "create-flow"},
        )
        assert "hunter2" not in rec.trajectory.spec.query.raw
        assert "[REDACTED_BEARER]" in rec.trajectory.spec.query.raw
        assert rec.trajectory.spec.query.normalized["intent"] == "create-flow"

    def test_record_observation_and_action(self, tmp_path: Path) -> None:
        rec = TrajectoryRecorder("p", "t", "rev", persist_dir=tmp_path)
        rec.set_query("req", {"intent": "x"})
        rec.record_observation(step_index=0, obs_type="pre-action", state={"flows": ["a"]})
        rec.record_action(
            step_index=0,
            action_type="flow.patch",
            normalized=("flow.patch", "addNode", "validator.json-schema", "after-sender", "single-required"),
            arguments_digest="abc123",
            result_status="applied",
            result_summary="applied=1",
        )
        assert len(rec.trajectory.spec.steps) == 1
        step = rec.trajectory.spec.steps[0]
        assert step.index == 0
        assert step.observation.type == "pre-action"
        assert step.action.type == "flow.patch"
        assert step.action.normalized == (
            "flow.patch",
            "addNode",
            "validator.json-schema",
            "after-sender",
            "single-required",
        )
        assert step.result.status == "applied"

    def test_finalize_persists_yaml(self, tmp_path: Path) -> None:
        rec = TrajectoryRecorder("p", "t", "rev", persist_dir=tmp_path)
        rec.set_query("req", {"intent": "x"})
        rec.record_observation(0, "pre-action", {"flows": []})
        rec.record_action(
            0,
            "flow.patch",
            ("flow.patch", "addNode", "log.message", "add-log.message", "single-required"),
            "digest",
            "applied",
            "ok",
        )
        path = rec.finalize("success", {"completion": 1.0})
        assert path.exists()
        assert path.suffix == ".yaml"
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert loaded["metadata"]["projectId"] == "p"
        assert loaded["spec"]["outcome"]["status"] == "success"
        assert loaded["spec"]["outcome"]["reward"]["completion"] == 1.0
        assert len(loaded["spec"]["steps"]) == 1
        # Normalized tuple should be persisted as a list (YAML-safe)
        assert loaded["spec"]["steps"][0]["action"]["normalized"] == [
            "flow.patch",
            "addNode",
            "log.message",
            "add-log.message",
            "single-required",
        ]

    def test_finalize_redacts_reward(self, tmp_path: Path) -> None:
        rec = TrajectoryRecorder("p", "t", "rev", persist_dir=tmp_path)
        rec.set_query("req", {"intent": "x"})
        path = rec.finalize("success", {"note": "password=hunter2"})
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "hunter2" not in yaml.safe_dump(loaded)

    def test_trajectory_records_three_steps(self, tmp_path: Path) -> None:
        rec = TrajectoryRecorder("p", "t", "rev", persist_dir=tmp_path)
        rec.set_query("req", {"intent": "x"})
        for i in range(3):
            rec.record_observation(i, "pre-action", {"i": i})
            rec.record_action(
                i,
                "flow.patch",
                ("flow.patch", "addNode", "log.message", "add-log.message", "single-required"),
                f"digest-{i}",
                "applied",
                f"step {i}",
            )
        rec.finalize("success", {})
        assert len(rec.trajectory.spec.steps) == 3
        for i, step in enumerate(rec.trajectory.spec.steps):
            assert step.index == i
            assert step.observation is not None
            assert step.action is not None
            assert step.result is not None

    def test_default_persist_dir_is_oiw_trajectories(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        rec = TrajectoryRecorder("p", "t", "rev")
        rec.set_query("req", {"intent": "x"})
        path = rec.finalize("success", {})
        assert path == tmp_path / ".oiw" / "trajectories" / f"{rec.trajectory_id}.yaml"
        assert path.exists()

    def test_secret_in_summary_is_redacted_on_persist(self, tmp_path: Path) -> None:
        rec = TrajectoryRecorder("p", "t", "rev", persist_dir=tmp_path)
        rec.set_query("req", {"intent": "x"})
        rec.record_observation(0, "pre-action", {"flows": []})
        rec.record_action(
            0,
            "flow.patch",
            ("flow.patch", "addNode", "validator.json-schema", "after-sender", "single-required"),
            "digest",
            "applied",
            "applied with password=hunter2",
        )
        path = rec.finalize("success", {})
        text = path.read_text(encoding="utf-8")
        assert "hunter2" not in text
        assert "[REDACTED]" in text
