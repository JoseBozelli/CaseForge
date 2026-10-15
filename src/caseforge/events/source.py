"""Raw source events as delivered by source adapters, before mapping."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from caseforge.common.hashing import sha256_hex
from caseforge.events.envelope import NonEmptyStr, UtcDatetime


class SourceEvent(BaseModel):
    """Source-specific event record.

    Type and actor names follow the source's own vocabulary; a MappingSpec
    translates them into canonical terms.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_system: NonEmptyStr
    source_event_id: NonEmptyStr
    source_type: NonEmptyStr
    tenant_id: NonEmptyStr
    entity_id: NonEmptyStr
    case_id: NonEmptyStr | None = None
    actor: NonEmptyStr
    actor_id: NonEmptyStr | None = None
    correlation_id: NonEmptyStr | None = None
    causation_id: NonEmptyStr | None = None
    occurred_at: UtcDatetime
    recorded_at: UtcDatetime
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    def content_sha256(self) -> str:
        """SHA-256 of the event's canonical-json-v1 serialization."""
        return sha256_hex(self.model_dump(mode="json"))
