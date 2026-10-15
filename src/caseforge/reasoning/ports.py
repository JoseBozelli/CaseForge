"""Reasoner port and reasoning errors."""

from __future__ import annotations

from typing import Protocol

from caseforge.reasoning.models import LlmCallRecord, ReasonerRequest, ReasonerResponse


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
