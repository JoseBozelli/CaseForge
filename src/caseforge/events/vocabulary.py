"""Canonical event vocabulary: event types, actors and entity types as validated data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from caseforge.common.errors import ConfigError
from caseforge.common.yaml_io import load_yaml_mapping
from caseforge.events.envelope import EventEnvelope

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*$")]
Name = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
EventTypeName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")]


class ViolationCode(StrEnum):
    """Stable reason codes for events that do not conform to the vocabulary."""

    UNKNOWN_EVENT_TYPE = "unknown_event_type"
    ACTOR_NOT_ALLOWED = "actor_not_allowed"
    ENTITY_TYPE_NOT_ALLOWED = "entity_type_not_allowed"
    MISSING_CASE_ID = "missing_case_id"
    MISSING_ATTRIBUTE = "missing_attribute"
    CANONICAL_VERSION_MISMATCH = "canonical_version_mismatch"


@dataclass(frozen=True)
class Violation:
    code: ViolationCode
    detail: str


class VocabularyViolationError(ValueError):
    """Raised when an event breaks one or more vocabulary rules."""

    def __init__(self, violations: tuple[Violation, ...]) -> None:
        self.violations = violations
        super().__init__("; ".join(f"{v.code}: {v.detail}" for v in violations))


class EventTypeSpec(BaseModel):
    """Rules for one canonical event type."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str = Field(min_length=1)
    entity_types: frozenset[Name] = Field(min_length=1)
    allowed_actors: frozenset[Name] = Field(min_length=1)
    required_attributes: frozenset[str] = frozenset()
    case_scoped: bool = True


class CanonicalVocabulary(BaseModel):
    """Versioned set of canonical event types the core accepts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vocabulary_id: Identifier
    version: int = Field(ge=1)
    description: str = Field(min_length=1)
    actors: frozenset[Name] = Field(min_length=1)
    entity_types: frozenset[Name] = Field(min_length=1)
    event_types: dict[EventTypeName, EventTypeSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_references(self) -> CanonicalVocabulary:
        problems: list[str] = []
        for name, spec in sorted(self.event_types.items()):
            unknown_actors = spec.allowed_actors - self.actors
            if unknown_actors:
                problems.append(f"{name}: undeclared actors {sorted(unknown_actors)}")
            unknown_entities = spec.entity_types - self.entity_types
            if unknown_entities:
                problems.append(f"{name}: undeclared entity types {sorted(unknown_entities)}")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def check(self, event: EventEnvelope) -> tuple[Violation, ...]:
        """Return every vocabulary violation in the event; an empty tuple means valid."""
        violations: list[Violation] = []
        if event.provenance.canonical_version != self.version:
            violations.append(
                Violation(
                    ViolationCode.CANONICAL_VERSION_MISMATCH,
                    f"event built for v{event.provenance.canonical_version}, "
                    f"vocabulary is v{self.version}",
                )
            )
        spec = self.event_types.get(event.event_type)
        if spec is None:
            violations.append(Violation(ViolationCode.UNKNOWN_EVENT_TYPE, event.event_type))
            return tuple(violations)
        if event.actor not in spec.allowed_actors:
            violations.append(Violation(ViolationCode.ACTOR_NOT_ALLOWED, event.actor))
        if event.entity_type not in spec.entity_types:
            violations.append(Violation(ViolationCode.ENTITY_TYPE_NOT_ALLOWED, event.entity_type))
        if spec.case_scoped and event.case_id is None:
            violations.append(Violation(ViolationCode.MISSING_CASE_ID, event.event_type))
        for name in sorted(spec.required_attributes):
            if event.attributes.get(name) is None:
                violations.append(Violation(ViolationCode.MISSING_ATTRIBUTE, name))
        return tuple(violations)

    def validate_event(self, event: EventEnvelope) -> None:
        """Raise VocabularyViolationError listing every violation, if any."""
        violations = self.check(event)
        if violations:
            raise VocabularyViolationError(violations)


def load_vocabulary(path: str | Path) -> CanonicalVocabulary:
    """Load and validate a canonical vocabulary YAML file."""
    data = load_yaml_mapping(path)
    try:
        return CanonicalVocabulary.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid canonical vocabulary in {path}:\n{exc}") from exc
