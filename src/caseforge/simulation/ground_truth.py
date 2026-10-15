"""Simulator-only ground truth. Agent-side code must never import this module."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue

from caseforge.events.envelope import NonEmptyStr


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
