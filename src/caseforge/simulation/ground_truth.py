"""Simulator-only ground truth. Agent-side code must never import this module."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue

from caseforge.events.envelope import NonEmptyStr, UtcDatetime


class ActionTruth(BaseModel):
    """Hidden effect of one applied action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: NonEmptyStr
    action_type: NonEmptyStr
    acted_at: UtcDatetime
    resolve_probability: float
    already_resolved: bool
    resolved: bool
    resolution_at: UtcDatetime | None
    outcome_observable: bool


class GroundTruth(BaseModel):
    """Hidden facts about one simulated world, used only by evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    family_id: NonEmptyStr
    spec_version: int
    seed: int
    world_seed: int
    case_id: NonEmptyStr
    blocker: NonEmptyStr
    effective_actions: tuple[NonEmptyStr, ...]
    variables: dict[str, JsonValue]
    occurred_event_ids: tuple[str, ...]
    dropped_event_ids: tuple[str, ...]
    actions: tuple[ActionTruth, ...] = ()
    resolved_by: str | None = None
