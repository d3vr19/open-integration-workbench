"""Tests route. Spec §21.1, §17."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from oiw.testing import run_tests
from pydantic import BaseModel

from ..models import TestResult
from ..workspace import load_project

router = APIRouter(prefix="/api/v1", tags=["Tests"])


class RunTestsRequest(BaseModel):
    flow_id: str | None = None
    test_name: str | None = None


@router.post("/projects/{project_id}/tests:run", response_model=list[TestResult])
def run_tests_endpoint(project_id: str, req: RunTestsRequest | None = None) -> list[TestResult]:
    flow_id = req.flow_id if req else None
    test_name = req.test_name if req else None
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc
    results = run_tests(project, flow_id=flow_id, test_name=test_name)
    return [
        TestResult(
            flow_id=r.flow_id,
            test_name=r.test_name,
            passed=r.passed,
            duration_ms=r.duration_ms,
            failures=r.failures,
        )
        for r in results
    ]
