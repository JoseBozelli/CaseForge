"""Boundary guards: the stop signal and wrappers that check it before model and tool calls.

EmergencyStopEngaged derives from BaseException on purpose. Workers, the supervisor
and the tool registry isolate failures with `except Exception`; a stop must pass
through that isolation instead of being handled as an ordinary error.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from caseforge.reasoning.models import ReasonerRequest, ReasonerResponse
from caseforge.reasoning.ports import Reasoner
from caseforge.tools.models import ToolCall, ToolContext, ToolErrorCode
from caseforge.tools.registry import ToolOutcome

Guard = Callable[[str], None]


class EmergencyStopEngaged(BaseException):  # noqa: N818 - a stop signal, not an error
    """Raised at a trusted boundary while the emergency stop is engaged."""


class GovernedReasoner:
    """Checks the guard before every model call."""

    def __init__(self, inner: Reasoner, guard: Guard) -> None:
        self._inner = inner
        self._guard = guard

    def complete(self, request: ReasonerRequest) -> ReasonerResponse:
        self._guard("reasoner")
        return self._inner.complete(request)


class ToolBudget(Protocol):
    def reserve_tool_call(self, run_id: str) -> Any: ...


class GovernedTools:
    """Checks the guard, then the run's tool budget, before every tool call."""

    def __init__(self, inner: Any, guard: Guard, budget: ToolBudget | None = None) -> None:
        self._inner = inner
        self._guard = guard
        self._budget = budget

    def describe(self, agent: str) -> list[dict[str, Any]]:
        return self._inner.describe(agent)

    def invoke(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        self._guard(f"tool:{call.tool}")
        if self._budget is not None:
            decision = self._budget.reserve_tool_call(context.run_id)
            if not decision.allowed:
                return self._inner.refuse(
                    call,
                    context,
                    ToolErrorCode.BUDGET_EXHAUSTED,
                    decision.reason or "tool budget exhausted",
                )
        return self._inner.invoke(call, context)
