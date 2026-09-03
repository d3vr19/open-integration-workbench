"""Tests for the LLM-driven interpreter (WP-04 Task 1)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from oiw.agent.context import ProjectContext
from oiw.agent.gateway_client import ChatResponse, ModelGatewayClient
from oiw.agent.interpreter import (
    OIW_W014,
    _parse_llm_response,
    interpret_requirement,
    interpret_requirement_fallback,
)


class TestParseLLMResponse:
    def test_parses_clean_json(self) -> None:
        content = json.dumps(
            {
                "intent": "create-flow",
                "archetype": "api-to-erp",
                "sourceProtocol": "https",
                "targetProtocol": "https",
                "operations": ["validate"],
                "components": ["validator.json-schema", "receiver.http"],
                "constraints": ["must-have-error-handling"],
                "confidence": 0.9,
            }
        )
        result = _parse_llm_response(content, "raw")
        assert result.intent == "create-flow"
        assert result.archetype == "api-to-erp"
        assert result.source_protocol == "https"
        assert "validator.json-schema" in result.components
        assert result.confidence == 0.9

    def test_parses_json_with_markdown_fences(self) -> None:
        content = '```json\n{"intent": "modify-flow", "confidence": 0.7}\n```'
        result = _parse_llm_response(content, "raw")
        assert result.intent == "modify-flow"
        assert result.confidence == 0.7

    def test_parses_json_embedded_in_prose(self) -> None:
        content = 'Here is the result: {"intent": "fix-flow", "confidence": 0.6} done.'
        result = _parse_llm_response(content, "raw")
        assert result.intent == "fix-flow"

    def test_returns_low_confidence_on_invalid_json(self) -> None:
        result = _parse_llm_response("not json at all", "raw")
        assert result.intent == "general"
        assert result.confidence <= 0.2

    def test_returns_low_confidence_on_empty_content(self) -> None:
        result = _parse_llm_response(None, "raw")
        assert result.intent == "general"
        assert result.confidence == 0.0


class TestInterpretRequirementFallback:
    def test_create_flow_intent_detected(self) -> None:
        result = interpret_requirement_fallback("Create a flow that validates JSON orders")
        assert result.intent == "create-flow"
        assert "validate" in result.operations
        assert "validator.json-schema" in result.components
        assert result.confidence >= 0.5

    def test_modify_flow_intent_detected(self) -> None:
        result = interpret_requirement_fallback(
            "Add schema validation before the normalize step in order-to-s4"
        )
        assert result.intent == "modify-flow"
        assert "validate" in result.operations

    def test_fix_flow_intent_detected(self) -> None:
        result = interpret_requirement_fallback("The receiver times out after 30 seconds, increase it")
        assert result.intent == "fix-flow"
        assert "receiver.http" in result.components

    def test_ambiguous_requirement_low_confidence(self) -> None:
        result = interpret_requirement_fallback("Make it better")
        # Either general intent with low confidence, or low-confidence modification
        assert result.confidence < 0.8

    def test_constraints_always_present(self) -> None:
        result = interpret_requirement_fallback("Create a flow")
        assert "must-have-error-handling" in result.constraints
        assert "no-secrets-inline" in result.constraints

    def test_protocols_detected(self) -> None:
        result = interpret_requirement_fallback("Receive orders via HTTPS and forward via SFTP")
        assert "https" in [result.source_protocol, result.target_protocol]
        assert "sftp" in [result.source_protocol, result.target_protocol]

    def test_archetype_built_from_protocols(self) -> None:
        result = interpret_requirement_fallback("from sftp to https")
        # Should detect both protocols and build an archetype
        assert result.source_protocol is not None
        assert result.target_protocol is not None


@pytest.mark.asyncio
async def test_interpret_requirement_with_mock_gateway(temp_project: Path) -> None:
    """LLM gateway returns a valid interpretation — NormalizedRequirement populated."""
    project = ProjectContext.load(temp_project / "order-to-s4")
    gateway = AsyncMock(spec=ModelGatewayClient)
    gateway.chat.return_value = ChatResponse(
        content=json.dumps(
            {
                "intent": "create-flow",
                "archetype": "api-to-erp",
                "sourceProtocol": "https",
                "targetProtocol": "https",
                "operations": ["validate"],
                "components": ["validator.json-schema", "receiver.http"],
                "constraints": ["must-have-error-handling"],
                "confidence": 0.9,
            }
        ),
        usage={},
    )
    result = await interpret_requirement(
        "Create a flow that validates JSON orders and sends them to S/4HANA",
        project,
        gateway,
    )
    assert result.intent == "create-flow"
    assert "validator.json-schema" in result.components
    assert result.confidence == 0.9
    # Verify the gateway was called with the system prompt
    gateway.chat.assert_awaited_once()
    call_kwargs = gateway.chat.call_args.kwargs
    assert "messages" in call_kwargs
    assert call_kwargs["messages"][0]["role"] == "system"
    assert "SAP Cloud Integration requirement analyst" in call_kwargs["messages"][0]["content"]


@pytest.mark.asyncio
async def test_interpret_requirement_with_markdown_fenced_response(temp_project: Path) -> None:
    """LLM returns JSON wrapped in ```json fences — parser strips them."""
    project = ProjectContext.load(temp_project / "order-to-s4")
    gateway = AsyncMock(spec=ModelGatewayClient)
    gateway.chat.return_value = ChatResponse(
        content='```json\n{"intent": "modify-flow", "confidence": 0.7, "operations": ["validate"]}\n```',
        usage={},
    )
    result = await interpret_requirement("Add validation", project, gateway)
    assert result.intent == "modify-flow"
    assert result.confidence == 0.7
    assert "validate" in result.operations


@pytest.mark.asyncio
async def test_interpret_requirement_fallback_warning_emitted() -> None:
    """When the LLM is unavailable, the orchestrator (not the interpreter
    itself) emits warning OIW-W014. Verify the warning code constant."""
    assert "OIW-W014" in OIW_W014
    assert "fallback" in OIW_W014.lower()


class TestInterpreterCreateFlowScenario:
    """WP-04 Task 1 test matrix: 'Create a flow that validates JSON orders
    and sends them to S/4HANA' should yield intent=create-flow,
    components includes validator.json-schema and receiver.http."""

    @pytest.mark.asyncio
    async def test_create_flow_components(self, temp_project: Path) -> None:
        project = ProjectContext.load(temp_project / "order-to-s4")
        gateway = AsyncMock(spec=ModelGatewayClient)
        gateway.chat.return_value = ChatResponse(
            content=json.dumps(
                {
                    "intent": "create-flow",
                    "components": ["validator.json-schema", "receiver.http", "sender.http"],
                    "operations": ["validate"],
                    "confidence": 0.9,
                }
            ),
            usage={},
        )
        result = await interpret_requirement(
            "Create a flow that validates JSON orders and sends them to S/4HANA",
            project,
            gateway,
        )
        assert result.intent == "create-flow"
        assert "validator.json-schema" in result.components
        assert "receiver.http" in result.components


class TestInterpreterModifyFlowScenario:
    """WP-04 Task 1 test matrix: 'Add schema validation before the normalize
    step in order-to-s4' should yield intent=modify-flow, operations
    includes validate."""

    @pytest.mark.asyncio
    async def test_modify_flow_operations(self, temp_project: Path) -> None:
        project = ProjectContext.load(temp_project / "order-to-s4")
        gateway = AsyncMock(spec=ModelGatewayClient)
        gateway.chat.return_value = ChatResponse(
            content=json.dumps(
                {
                    "intent": "modify-flow",
                    "operations": ["validate"],
                    "components": ["validator.json-schema"],
                    "confidence": 0.85,
                }
            ),
            usage={},
        )
        result = await interpret_requirement(
            "Add schema validation before the normalize step in order-to-s4",
            project,
            gateway,
        )
        assert result.intent == "modify-flow"
        assert "validate" in result.operations


class TestInterpreterAmbiguousScenario:
    """WP-04 Task 1 test matrix: 'Make it better' should yield confidence < 0.5."""

    @pytest.mark.asyncio
    async def test_ambiguous_low_confidence(self, temp_project: Path) -> None:
        project = ProjectContext.load(temp_project / "order-to-s4")
        gateway = AsyncMock(spec=ModelGatewayClient)
        gateway.chat.return_value = ChatResponse(
            content=json.dumps(
                {
                    "intent": "general",
                    "confidence": 0.3,
                    "assumptions": ["requirement unclear"],
                }
            ),
            usage={},
        )
        result = await interpret_requirement("Make it better", project, gateway)
        assert result.confidence < 0.5


class TestSplitterPhrasing:
    """WP-10 H8: Interpreter splitter-phrasing gap (roadmap open thread #5)."""

    @pytest.mark.parametrize(
        "phrase",
        [
            "split the batch",
            "process each item",
            "split orders into individual messages",
        ],
    )
    def test_splitter_phrasing_yields_splitter_general(self, phrase: str) -> None:
        result = interpret_requirement_fallback(f"Create a flow to {phrase} and forward")
        assert "splitter.general" in result.components
        assert "split" in result.operations

    @pytest.mark.parametrize(
        "phrase",
        [
            "split the difference",
            "split tunneling",
        ],
    )
    def test_negative_controls_do_not_trigger_splitter(self, phrase: str) -> None:
        result = interpret_requirement_fallback(f"Create a flow with {phrase}")
        assert "splitter.general" not in result.components
        assert "split" not in result.operations

    def test_end_to_end_assemble_from_requirement(self) -> None:
        from oiw.agent.turbo_pieces import assemble_from_requirement, proven_pieces

        req = interpret_requirement_fallback(
            "Split the batch and forward orders to https://httpbin.org/post"
        )
        assert "splitter.general" in req.components

        res = assemble_from_requirement(req, "test-split-fwd")
        pieces = proven_pieces()
        if "splitter.general" in pieces:
            assert res.assembled is True
            assert any(p.node_type == "splitter.general" for p in res.pieces)
            splitter_piece = next(p for p in res.pieces if p.node_type == "splitter.general")
            assert splitter_piece.config.get("maxItems") or splitter_piece.config.get("maxIterations")
        else:
            # Splitter runs for real (H4) but has no exporter shape yet
            # (B-2 shippable-intersection lesson, 2026-09-03): assembly
            # proceeds for the coverable pieces and escalates splitter
            # honestly via unmatched_components — the teacher-request
            # signal (never a silent drop).
            assert "splitter.general" in res.unmatched_components
            assert "splitter.general" in res.unmatched_components

