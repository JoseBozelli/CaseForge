"""Governance records."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from caseforge.events.envelope import NonEmptyStr, UtcDatetime


class AuditEntry(BaseModel):
    """One governance decision or operation. The audit log is append-only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int | None = None
    at: UtcDatetime
    actor: NonEmptyStr
    action: NonEmptyStr
    target: NonEmptyStr
    outcome: Literal["allowed", "denied", "recorded"]
    detail: dict[str, JsonValue] = Field(default_factory=dict)
