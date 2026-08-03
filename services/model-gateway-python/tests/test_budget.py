"""Tests for the budget tracker and circuit breaker.

Spec ref: §12.7 (policies: maxTokensPerProjectPerDay, circuitBreaker).
"""

from __future__ import annotations

import time

from oiw_gateway.budget import BudgetTracker, CircuitBreaker

# ---------------------------------------------------------------------
# BudgetTracker
# ---------------------------------------------------------------------


def test_budget_check_allowed() -> None:
    tracker = BudgetTracker(max_tokens_per_day=10000)
    assert tracker.check("proj-1", 1000) is True


def test_budget_check_exhausted() -> None:
    tracker = BudgetTracker(max_tokens_per_day=100)
    tracker.record("proj-1", 100)
    assert tracker.check("proj-1", 1) is False


def test_budget_check_would_exceed() -> None:
    tracker = BudgetTracker(max_tokens_per_day=100)
    tracker.record("proj-1", 80)
    # 80 + 30 = 110 > 100 → should be rejected
    assert tracker.check("proj-1", 30) is False


def test_budget_check_separate_projects() -> None:
    tracker = BudgetTracker(max_tokens_per_day=100)
    tracker.record("proj-1", 100)
    # proj-2 has a separate budget
    assert tracker.check("proj-2", 50) is True


def test_budget_get_status() -> None:
    tracker = BudgetTracker(max_tokens_per_day=10000)
    tracker.record("proj-1", 500)
    status = tracker.get_status("proj-1")
    assert status.project_id == "proj-1"
    assert status.tokens_used_today == 500
    assert status.max_tokens_per_day == 10000
    assert status.remaining == 9500
    assert status.exhausted is False
    assert status.requests_today == 1


def test_budget_exhausted_status() -> None:
    tracker = BudgetTracker(max_tokens_per_day=100)
    tracker.record("proj-1", 100)
    status = tracker.get_status("proj-1")
    assert status.exhausted is True
    assert status.remaining == 0


def test_budget_multiple_requests_tracked() -> None:
    tracker = BudgetTracker(max_tokens_per_day=10000)
    tracker.record("proj-1", 100)
    tracker.record("proj-1", 200)
    tracker.record("proj-1", 300)
    status = tracker.get_status("proj-1")
    assert status.tokens_used_today == 600
    assert status.requests_today == 3


# ---------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------


def test_circuit_breaker_starts_closed() -> None:
    cb = CircuitBreaker(failure_threshold=5, reset_timeout_seconds=60)
    state = cb.get_state("anthropic")
    assert state.state == "closed"
    assert state.failure_count == 0
    assert cb.can_call("anthropic") is True


def test_circuit_breaker_trips_after_threshold() -> None:
    cb = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=60)
    cb.record_failure("anthropic")
    cb.record_failure("anthropic")
    assert cb.can_call("anthropic") is True  # 2 failures, threshold is 3
    cb.record_failure("anthropic")
    assert cb.can_call("anthropic") is False  # tripped
    state = cb.get_state("anthropic")
    assert state.state == "open"


def test_circuit_breaker_resets_on_success() -> None:
    cb = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=60)
    cb.record_failure("anthropic")
    cb.record_failure("anthropic")
    cb.record_success("anthropic")
    state = cb.get_state("anthropic")
    assert state.state == "closed"
    assert state.failure_count == 0


def test_circuit_breaker_half_open_after_timeout() -> None:
    cb = CircuitBreaker(failure_threshold=2, reset_timeout_seconds=1)
    cb.record_failure("openai")
    cb.record_failure("openai")
    assert cb.can_call("openai") is False
    # Wait for the timeout to pass
    time.sleep(1.1)
    assert cb.can_call("openai") is True  # half-open: one request allowed
    state = cb.get_state("openai")
    assert state.state == "half-open"


def test_circuit_breaker_separate_providers() -> None:
    cb = CircuitBreaker(failure_threshold=2, reset_timeout_seconds=60)
    cb.record_failure("anthropic")
    cb.record_failure("anthropic")
    # Anthropic is tripped but OpenAI should be fine
    assert cb.can_call("anthropic") is False
    assert cb.can_call("openai") is True
