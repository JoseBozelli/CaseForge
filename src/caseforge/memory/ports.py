"""Episodic memory port."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from caseforge.events.envelope import NonEmptyStr


class EpisodeSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    episode_id: NonEmptyStr
    case_id: NonEmptyStr
    summary: NonEmptyStr
    action_type: NonEmptyStr
    outcome_status: NonEmptyStr
    score: float


class EpisodeProvider(Protocol):
    def search(
        self, tenant_id: str, query: str, top_k: int, exclude_case_id: str | None = None
    ) -> tuple[EpisodeSummary, ...]: ...
