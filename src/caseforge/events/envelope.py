"""Canonical event envelope shared by every source after normalization."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Final, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

ENVELOPE_SCHEMA_VERSION: Final = "event.v1"

NonEmptyStr = Annotated[str, Field(min_length=1)]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class EventProvenance(BaseModel):
    """Origin of a canonical event: source identity and the mapping that produced it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_system: NonEmptyStr
    source_event_type: NonEmptyStr
    source_event_id: NonEmptyStr
    mapping_id: NonEmptyStr
    mapping_version: int = Field(ge=1)
    canonical_version: int = Field(ge=1)
    raw_sha256: Sha256Hex


class EventEnvelope(BaseModel):
    """Source-independent event record consumed by the CaseForge core.

    Timestamps must be timezone-aware and are normalized to UTC. Vocabulary rules
    (allowed types, actors, entities and attributes) are checked separately by
    CanonicalVocabulary, so the envelope stays domain-neutral.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["event.v1"] = ENVELOPE_SCHEMA_VERSION
    event_id: NonEmptyStr
    event_type: NonEmptyStr
    tenant_id: NonEmptyStr
    entity_type: NonEmptyStr
    entity_id: NonEmptyStr
    case_id: NonEmptyStr | None = None
    actor: NonEmptyStr
    actor_id: NonEmptyStr | None = None
    correlation_id: NonEmptyStr
    causation_id: NonEmptyStr | None = None
    occurred_at: AwareDatetime
    recorded_at: AwareDatetime
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    provenance: EventProvenance

    @field_validator("occurred_at", "recorded_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _check_consistency(self) -> EventEnvelope:
        if self.recorded_at < self.occurred_at:
            raise ValueError("recorded_at must not precede occurred_at")
        if self.causation_id == self.event_id:
            raise ValueError("causation_id must not equal event_id")
        return self
