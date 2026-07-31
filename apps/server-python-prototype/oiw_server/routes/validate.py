"""Validation route. Spec §21.1, §14."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from oiw.schema_validator import SchemaError, validate_project
from oiw.validators.graph import validate_flow_graph
from oiw.validators.rules import run_rule_validators
from pydantic import BaseModel

from ..models import ValidationResult
from ..workspace import load_project

router = APIRouter(prefix="/api/v1", tags=["Validation"])


class ValidateRequest(BaseModel):
    strict: bool = False


@router.post("/projects/{project_id}/validate", response_model=ValidationResult)
def validate_project_endpoint(project_id: str, req: ValidateRequest | None = None) -> ValidationResult:
    strict = req.strict if req else False
    try:
        project = load_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc}") from exc

    errors: list[str] = []
    warnings: list[str] = []

    # 1. JSON Schema validation
    try:
        schema_results = validate_project(project)
    except SchemaError as exc:
        raise HTTPException(status_code=500, detail=f"schema error: {exc}") from exc
    errors.extend(schema_results.errors)
    warnings.extend(schema_results.warnings)

    # 2. Semantic graph validation
    for flow in project.flows:
        graph_errors, graph_warnings = validate_flow_graph(flow)
        errors.extend(graph_errors)
        warnings.extend(graph_warnings)

    # 3. Rule-based validators
    rule_errors, rule_warnings = run_rule_validators(project)
    errors.extend(rule_errors)
    warnings.extend(rule_warnings)

    if strict:
        errors.extend(warnings)
        warnings = []

    return ValidationResult(
        errors=errors,
        warnings=warnings,
        error_count=len(errors),
        warning_count=len(warnings),
        passed=len(errors) == 0,
    )
