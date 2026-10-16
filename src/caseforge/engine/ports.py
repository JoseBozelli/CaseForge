"""Ports through which the engine reaches case data, actions and outcomes."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from caseforge.events.source import SourceEvent
from caseforge.outcomes.models import OutcomeObservation


class CaseSource(Protocol):
    def source_events(
        self, tenant_id: str, case_id: str, as_of: datetime
    ) -> tuple[SourceEvent, ...]: ...


class ActionExecutor(Protocol):
    supports_idempotency_keys: bool
    """True when the external system ignores repeats of the same action id."""

    def execute(
        self, *, tenant_id: str, case_id: str, action_id: str, action_type: str, at: datetime
    ) -> bool:
        """Apply an action; False when this action_id was already applied."""
        ...


class OutcomeSource(Protocol):
    def observe(
        self, *, tenant_id: str, case_id: str, action_id: str, as_of: datetime
    ) -> OutcomeObservation: ...
