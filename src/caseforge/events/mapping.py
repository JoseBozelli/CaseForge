"""Source-to-canonical event mapping: versioned YAML rules and deterministic normalization."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from caseforge.common.errors import ConfigError
from caseforge.common.yaml_io import load_yaml_mapping
from caseforge.events.envelope import EventEnvelope, EventProvenance, NonEmptyStr
from caseforge.events.source import SourceEvent
from caseforge.events.vocabulary import (
    CanonicalVocabulary,
    EventTypeName,
    Identifier,
    Name,
    Violation,
)

JsonScalar = str | int | float | bool | None
_ABSENT = object()


def _same(a: Any, b: Any) -> bool:
    """Equality that also requires identical types, so True never equals 1."""
    return type(a) is type(b) and a == b


class MatchSpec(BaseModel):
    """Selects source events by type and optional exact attribute values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_type: NonEmptyStr
    where: dict[str, JsonScalar] = Field(default_factory=dict)

    def matches(self, event: SourceEvent) -> bool:
        if event.source_type != self.source_type:
            return False
        return all(_same(event.attributes.get(k, _ABSENT), v) for k, v in self.where.items())

    def overlaps(self, other: MatchSpec) -> bool:
        """True when some source event could satisfy both selectors."""
        if self.source_type != other.source_type:
            return False
        shared = self.where.keys() & other.where.keys()
        return all(_same(self.where[k], other.where[k]) for k in shared)


class MappingRule(BaseModel):
    """Translates matching source events into one canonical event type."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    match: MatchSpec
    canonical_type: EventTypeName
    entity_type: Name
    attribute_map: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_targets(self) -> MappingRule:
        targets = list(self.attribute_map.values())
        duplicates = sorted({t for t in targets if targets.count(t) > 1})
        if duplicates:
            raise ValueError(f"duplicate attribute targets {duplicates}")
        return self


class RejectRule(BaseModel):
    """Declares source events that must be rejected, with a documented reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    match: MatchSpec
    reason: NonEmptyStr


class MappingSpec(BaseModel):
    """Versioned mapping from one source system's vocabulary to a canonical vocabulary.

    Only attributes listed in a rule's attribute_map are carried into the canonical
    event. Source events matched by no rule are rejected as unmapped.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mapping_id: Identifier
    mapping_version: int = Field(ge=1)
    canonical_version: int = Field(ge=1)
    source_system: NonEmptyStr
    actor_map: dict[NonEmptyStr, Name] = Field(min_length=1)
    rules: tuple[MappingRule, ...] = Field(min_length=1)
    reject: tuple[RejectRule, ...] = ()

    @model_validator(mode="after")
    def _no_overlapping_rules(self) -> MappingSpec:
        problems = [
            f"rules {i} and {j} overlap (source_type {a.match.source_type!r})"
            for (i, a), (j, b) in combinations(enumerate(self.rules), 2)
            if a.match.overlaps(b.match)
        ]
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def check_against(self, vocabulary: CanonicalVocabulary) -> list[str]:
        """Return every incompatibility with the vocabulary; an empty list means compatible."""
        problems: list[str] = []
        if self.canonical_version != vocabulary.version:
            problems.append(
                f"canonical_version {self.canonical_version} does not match "
                f"vocabulary version {vocabulary.version}"
            )
        mapped_actors = set(self.actor_map.values())
        unknown_actors = mapped_actors - vocabulary.actors
        if unknown_actors:
            problems.append(f"actor_map maps to undeclared actors {sorted(unknown_actors)}")
        for index, rule in enumerate(self.rules):
            label = f"rule {index} ({rule.match.source_type!r})"
            spec = vocabulary.event_types.get(rule.canonical_type)
            if spec is None:
                problems.append(f"{label}: unknown canonical type {rule.canonical_type!r}")
                continue
            if rule.entity_type not in spec.entity_types:
                problems.append(
                    f"{label}: entity type {rule.entity_type!r} "
                    f"not allowed for {rule.canonical_type}"
                )
            missing = sorted(spec.required_attributes - set(rule.attribute_map.values()))
            if missing:
                problems.append(f"{label}: does not map required attributes {missing}")
            if not mapped_actors & spec.allowed_actors:
                problems.append(f"{label}: no mapped actor is allowed for {rule.canonical_type}")
        return problems


class RejectionCode(StrEnum):
    """Stable reason codes for source events that cannot be normalized."""

    WRONG_SOURCE = "wrong_source"
    EXPLICIT_REJECT = "explicit_reject"
    UNMAPPED = "unmapped"
    AMBIGUOUS = "ambiguous"
    ACTOR_NOT_MAPPED = "actor_not_mapped"
    INVALID_ENVELOPE = "invalid_envelope"
    VOCABULARY_VIOLATION = "vocabulary_violation"


@dataclass(frozen=True)
class Rejection:
    """Traceable record of a source event that was not normalized."""

    source_system: str
    source_event_id: str
    source_type: str
    code: RejectionCode
    detail: str
    mapping_id: str
    mapping_version: int
    raw_sha256: str
    violations: tuple[Violation, ...] = ()


@dataclass(frozen=True)
class NormalizationResult:
    accepted: tuple[EventEnvelope, ...]
    rejected: tuple[Rejection, ...]


def ensure_compatible(spec: MappingSpec, vocabulary: CanonicalVocabulary, origin: str) -> None:
    """Raise ConfigError when the mapping cannot produce valid canonical events."""
    problems = spec.check_against(vocabulary)
    if problems:
        raise ConfigError(
            f"mapping {spec.mapping_id!r} from {origin} is incompatible with vocabulary "
            f"{vocabulary.vocabulary_id!r} v{vocabulary.version}: " + "; ".join(problems)
        )


def load_mapping(path: str | Path, vocabulary: CanonicalVocabulary) -> MappingSpec:
    """Load a mapping YAML file and validate it against the canonical vocabulary."""
    data = load_yaml_mapping(path)
    try:
        spec = MappingSpec.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid mapping in {path}:\n{exc}") from exc
    ensure_compatible(spec, vocabulary, str(path))
    return spec


def _summarize(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or 'event'}: {err['msg']}"
        for err in exc.errors()
    )


class EventNormalizer:
    """Deterministically converts source events into canonical events or rejections."""

    def __init__(self, spec: MappingSpec, vocabulary: CanonicalVocabulary) -> None:
        ensure_compatible(spec, vocabulary, "EventNormalizer")
        self._spec = spec
        self._vocabulary = vocabulary

    def normalize(self, event: SourceEvent) -> EventEnvelope | Rejection:
        spec = self._spec
        if event.source_system != spec.source_system:
            return self._reject(
                event, RejectionCode.WRONG_SOURCE, f"mapping expects {spec.source_system!r}"
            )
        for reject_rule in spec.reject:
            if reject_rule.match.matches(event):
                return self._reject(event, RejectionCode.EXPLICIT_REJECT, reject_rule.reason)
        candidates = [rule for rule in spec.rules if rule.match.matches(event)]
        if not candidates:
            return self._reject(event, RejectionCode.UNMAPPED, event.source_type)
        if len(candidates) > 1:
            return self._reject(event, RejectionCode.AMBIGUOUS, f"{len(candidates)} rules match")
        rule = candidates[0]
        actor = spec.actor_map.get(event.actor)
        if actor is None:
            return self._reject(event, RejectionCode.ACTOR_NOT_MAPPED, event.actor)
        attributes = {
            target: event.attributes[source]
            for source, target in rule.attribute_map.items()
            if source in event.attributes
        }
        try:
            envelope = EventEnvelope(
                event_id=self._canonical_id(event.source_event_id),
                event_type=rule.canonical_type,
                tenant_id=event.tenant_id,
                entity_type=rule.entity_type,
                entity_id=event.entity_id,
                case_id=event.case_id,
                actor=actor,
                actor_id=event.actor_id,
                correlation_id=event.correlation_id or event.case_id or event.entity_id,
                causation_id=(
                    self._canonical_id(event.causation_id) if event.causation_id else None
                ),
                occurred_at=event.occurred_at,
                recorded_at=event.recorded_at,
                attributes=attributes,
                provenance=EventProvenance(
                    source_system=event.source_system,
                    source_event_type=event.source_type,
                    source_event_id=event.source_event_id,
                    mapping_id=spec.mapping_id,
                    mapping_version=spec.mapping_version,
                    canonical_version=spec.canonical_version,
                    raw_sha256=event.content_sha256(),
                ),
            )
        except ValidationError as exc:
            return self._reject(event, RejectionCode.INVALID_ENVELOPE, _summarize(exc))
        violations = self._vocabulary.check(envelope)
        if violations:
            detail = "; ".join(f"{v.code}: {v.detail}" for v in violations)
            return self._reject(event, RejectionCode.VOCABULARY_VIOLATION, detail, violations)
        return envelope

    def normalize_batch(self, events: Iterable[SourceEvent]) -> NormalizationResult:
        accepted: list[EventEnvelope] = []
        rejected: list[Rejection] = []
        for event in events:
            result = self.normalize(event)
            if isinstance(result, Rejection):
                rejected.append(result)
            else:
                accepted.append(result)
        return NormalizationResult(tuple(accepted), tuple(rejected))

    def _canonical_id(self, source_event_id: str) -> str:
        return f"{self._spec.source_system}:{source_event_id}"

    def _reject(
        self,
        event: SourceEvent,
        code: RejectionCode,
        detail: str,
        violations: tuple[Violation, ...] = (),
    ) -> Rejection:
        return Rejection(
            source_system=event.source_system,
            source_event_id=event.source_event_id,
            source_type=event.source_type,
            code=code,
            detail=detail,
            mapping_id=self._spec.mapping_id,
            mapping_version=self._spec.mapping_version,
            raw_sha256=event.content_sha256(),
            violations=violations,
        )
