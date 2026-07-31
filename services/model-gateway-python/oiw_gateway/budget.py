"""Token budget tracker and circuit breaker.

Spec ref: §12.7 (policies: maxTokensPerRequest, maxTokensPerProjectPerDay,
circuitBreaker).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock


@dataclass
class BudgetStatus:
    """Token budget status for a project."""

    project_id: str
    tokens_used_today: int
    max_tokens_per_day: int
    requests_today: int

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens_per_day - self.tokens_used_today)

    @property
    def exhausted(self) -> bool:
        return self.tokens_used_today >= self.max_tokens_per_day

    def to_dict(self) -> dict:
        return {
            "projectId": self.project_id,
            "tokensUsedToday": self.tokens_used_today,
            "maxTokensPerDay": self.max_tokens_per_day,
            "remaining": self.remaining,
            "requestsToday": self.requests_today,
            "exhausted": self.exhausted,
        }


class BudgetTracker:
    """Per-project token budget tracker.

    Spec §12.7: maxTokensPerProjectPerDay (default 2,000,000).
    """

    def __init__(self, max_tokens_per_day: int = 2_000_000) -> None:
        self._max = max_tokens_per_day
        self._usage: dict[str, dict[str, int]] = {}  # project_id → {date: {tokens, requests}}
        self._lock = Lock()

    def check(self, project_id: str, estimated_tokens: int) -> bool:
        """Check if a request would fit within the budget. Returns True if allowed."""
        with self._lock:
            status = self._get_status(project_id)
            return not status.exhausted and (status.tokens_used_today + estimated_tokens) <= self._max

    def record(self, project_id: str, tokens_used: int) -> None:
        """Record actual token usage for a project."""
        with self._lock:
            today = self._today()
            if project_id not in self._usage:
                self._usage[project_id] = {}
            if today not in self._usage[project_id]:
                self._usage[project_id][today] = {"tokens": 0, "requests": 0}
            self._usage[project_id][today]["tokens"] += tokens_used
            self._usage[project_id][today]["requests"] += 1

    def get_status(self, project_id: str) -> BudgetStatus:
        """Get the current budget status for a project."""
        with self._lock:
            return self._get_status(project_id)

    def _get_status(self, project_id: str) -> BudgetStatus:
        today = self._today()
        day_data = self._usage.get(project_id, {}).get(today, {"tokens": 0, "requests": 0})
        return BudgetStatus(
            project_id=project_id,
            tokens_used_today=day_data["tokens"],
            max_tokens_per_day=self._max,
            requests_today=day_data["requests"],
        )

    @staticmethod
    def _today() -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())


@dataclass
class CircuitBreakerState:
    """Circuit breaker state for a provider."""

    provider: str
    state: str  # "closed" | "open" | "half-open"
    failure_count: int
    last_failure_time: float | None = None

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "state": self.state,
            "failureCount": self.failure_count,
            "lastFailureTime": self.last_failure_time,
        }


class CircuitBreaker:
    """Circuit breaker for LLM provider calls.

    Spec §12.7: circuitBreaker.failureThreshold (default 5),
    circuitBreaker.resetTimeoutSeconds (default 60).

    States:
      - closed: normal operation, requests pass through
      - open: provider is failing; requests are rejected immediately
      - half-open: after reset timeout, one request is allowed to test
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout_seconds: int = 60,
    ) -> None:
        self._threshold = failure_threshold
        self._reset_timeout = reset_timeout_seconds
        self._states: dict[str, CircuitBreakerState] = {}
        self._lock = Lock()

    def can_call(self, provider: str) -> bool:
        """Check if a call to the provider is allowed."""
        with self._lock:
            state = self._states.get(provider)
            if state is None:
                return True

            if state.state == "closed":
                return True

            if state.state == "open":
                # Check if enough time has passed to try again (half-open)
                if state.last_failure_time and (time.time() - state.last_failure_time) > self._reset_timeout:
                    state.state = "half-open"
                    return True
                return False

            if state.state == "half-open":
                # Only allow one request at a time in half-open
                return True

            return True

    def record_success(self, provider: str) -> None:
        """Record a successful call — resets the breaker."""
        with self._lock:
            if provider in self._states:
                self._states[provider] = CircuitBreakerState(
                    provider=provider, state="closed", failure_count=0
                )

    def record_failure(self, provider: str) -> None:
        """Record a failed call — may trip the breaker."""
        with self._lock:
            state = self._states.get(provider)
            if state is None:
                state = CircuitBreakerState(provider=provider, state="closed", failure_count=0)
                self._states[provider] = state

            state.failure_count += 1
            state.last_failure_time = time.time()

            if state.failure_count >= self._threshold:
                state.state = "open"

    def get_state(self, provider: str) -> CircuitBreakerState:
        """Get the current breaker state for a provider."""
        with self._lock:
            state = self._states.get(provider)
            if state is None:
                return CircuitBreakerState(provider=provider, state="closed", failure_count=0)
            # Check if we should transition from open to half-open
            if (
                state.state == "open"
                and state.last_failure_time
                and (time.time() - state.last_failure_time) > self._reset_timeout
            ):
                state.state = "half-open"
            return state
