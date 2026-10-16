"""Boundary guards: the stop signal, and wrappers that check stop, breakers and budgets
before model calls, tool calls and external actions.

EmergencyStopEngaged derives from BaseException on purpose. Workers, the supervisor
and the tool registry isolate failures with `except Exception`; a stop must pass
through that isolation instead of being handled as an ordinary error.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from caseforge.reasoning.models import ReasonerRequest, ReasonerResponse
from caseforge.reasoning.ports import CircuitOpen, Reasoner, ReasonerError
from caseforge.tools.models import ToolCall, ToolContext, ToolErrorCode
from caseforge.tools.registry import ToolOutcome

Guard = Callable[[str], None]


class EmergencyStopEngaged(BaseException):  # noqa: N818 - a stop signal, not an error
    """Raised at a trusted boundary while the emergency stop is engaged."""


class CircuitOpenError(RuntimeError):
    """An external action was refused because the executor's circuit breaker is open."""


class Breakers(Protocol):
    def breaker_allows(self, resource: str) -> bool: ...

    def breaker_success(self, resource: str) -> Any: ...

    def breaker_failure(self, resource: str) -> Any: ...


class ToolBudget(Protocol):
    def reserve_tool_call(self, run_id: str) -> Any: ...


class GovernedReasoner:
    """Checks the stop and the reasoner breaker before every model call."""

    def __init__(self, inner: Reasoner, guard: Guard, breakers: Breakers | None = None) -> None:
        self._inner = inner
        self._guard = guard
        self._breakers = breakers

    def complete(self, request: ReasonerRequest) -> ReasonerResponse:
        self._guard("reasoner")
        if self._breakers is not None and not self._breakers.breaker_allows("reasoner"):
            raise CircuitOpen("reasoner circuit is open")
        try:
            response = self._inner.complete(request)
        except ReasonerError:
            if self._breakers is not None:
                self._breakers.breaker_failure("reasoner")
            raise
        if self._breakers is not None:
            self._breakers.breaker_success("reasoner")
        return response


class GovernedTools:
    """Checks the stop, the tool's breaker and the run's tool budget before every tool call."""

    def __init__(
        self,
        inner: Any,
        guard: Guard,
        budget: ToolBudget | None = None,
        breakers: Breakers | None = None,
    ) -> None:
        self._inner = inner
        self._guard = guard
        self._budget = budget
        self._breakers = breakers

    def describe(self, agent: str) -> list[dict[str, Any]]:
        return self._inner.describe(agent)

    def invoke(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        self._guard(f"tool:{call.tool}")
        resource = f"tool:{call.tool}"
        if self._breakers is not None and not self._breakers.breaker_allows(resource):
            return self._inner.refuse(
                call, context, ToolErrorCode.CIRCUIT_OPEN, f"{resource} circuit is open"
            )
        if self._budget is not None:
            decision = self._budget.reserve_tool_call(context.run_id)
            if not decision.allowed:
                return self._inner.refuse(
                    call,
                    context,
                    ToolErrorCode.BUDGET_EXHAUSTED,
                    decision.reason or "tool budget exhausted",
                )
        outcome = self._inner.invoke(call, context)
        if self._breakers is not None:
            if outcome.result.error_code == ToolErrorCode.TOOL_ERROR:
                self._breakers.breaker_failure(resource)
            elif outcome.result.ok:
                self._breakers.breaker_success(resource)
        return outcome


class GovernedExecutor:
    """Checks the executor breaker and retries with backoff, but only when the outside
    world ignores repeated action ids; otherwise a single attempt is made."""

    def __init__(
        self,
        inner: Any,
        breakers: Breakers,
        *,
        max_attempts: int,
        backoff_seconds: float,
        sleep: Callable[[float], None],
    ) -> None:
        self._inner = inner
        self._breakers = breakers
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._sleep = sleep

    @property
    def supports_idempotency_keys(self) -> bool:
        return bool(self._inner.supports_idempotency_keys)

    def execute(
        self, *, tenant_id: str, case_id: str, action_id: str, action_type: str, at: datetime
    ) -> bool:
        if not self._breakers.breaker_allows("executor"):
            raise CircuitOpenError("executor circuit is open")
        attempts = self._max_attempts if self.supports_idempotency_keys else 1
        for attempt in range(attempts):
            try:
                applied = self._inner.execute(
                    tenant_id=tenant_id,
                    case_id=case_id,
                    action_id=action_id,
                    action_type=action_type,
                    at=at,
                )
            except Exception:
                self._breakers.breaker_failure("executor")
                if attempt == attempts - 1 or not self._breakers.breaker_allows("executor"):
                    raise
                self._sleep(self._backoff * 2**attempt)
            else:
                self._breakers.breaker_success("executor")
                return applied
        raise AssertionError("unreachable")  # pragma: no cover
