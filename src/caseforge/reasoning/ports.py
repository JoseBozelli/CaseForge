"""Reasoner port and reasoning errors."""

from __future__ import annotations

from typing import Protocol

from caseforge.reasoning.models import (
    CallContext,
    LlmCallRecord,
    ReasonerRequest,
    ReasonerResponse,
    TokenUsage,
)


class ReasonerError(RuntimeError):
    """A reasoner could not produce a response."""


class ReplayMismatchError(ReasonerError):
    """Replay has no recorded response for this exact request."""


class ReasonerCallError(ReasonerError):
    """A structured call failed; carries the provenance record of the failed call."""

    def __init__(self, message: str, record: LlmCallRecord) -> None:
        super().__init__(message)
        self.record = record


class OutputValidationError(ReasonerCallError):
    """The response did not match the expected output schema."""


class Reasoner(Protocol):
    def complete(self, request: ReasonerRequest) -> ReasonerResponse: ...


class BudgetExhausted(ReasonerError):
    """A model call was refused because the run's budget is spent."""


class CallBudget(Protocol):
    """Checked by StructuredCaller around every model call."""

    def before_call(self, context: CallContext) -> None:
        """Reserve one call or raise BudgetExhausted."""
        ...

    def after_call(self, context: CallContext, usage: TokenUsage) -> None: ...
