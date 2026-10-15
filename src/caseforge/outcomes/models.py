"""Outcome observation contract: what is knowable about an action's result at a given time."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from caseforge.events.envelope import NonEmptyStr, UtcDatetime


class OutcomeStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"
    UNOBSERVABLE = "unobservable"


class OutcomeObservation(BaseModel):
    """Observed status of one action's outcome as of a point in time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: NonEmptyStr
    action_type: NonEmptyStr
    status: OutcomeStatus
    acted_at: UtcDatetime
    horizon_end: UtcDatetime
    observed_at: UtcDatetime | None = None
