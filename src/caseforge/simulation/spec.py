"""Scenario family specifications: latent blockers, event templates and observation noise."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from caseforge.common.errors import ConfigError
from caseforge.common.yaml_io import load_yaml_mapping
from caseforge.events.envelope import NonEmptyStr
from caseforge.events.mapping import JsonScalar
from caseforge.events.vocabulary import Identifier, Name

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
Minutes = Annotated[int, Field(ge=0)]
MinuteRange = tuple[Minutes, Minutes]


def _check_range(value: MinuteRange, label: str) -> None:
    if value[0] > value[1]:
        raise ValueError(f"{label} minimum exceeds maximum")


class _Spec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AtMinutes(_Spec):
    """Timestamp attribute: world start plus a fixed number of minutes (ISO 8601, UTC)."""

    at_minutes: Minutes


class Choice(_Spec):
    """Attribute drawn uniformly from the listed values."""

    choice: tuple[JsonScalar, ...] = Field(min_length=1)


class Var(_Spec):
    """Attribute taken from a world-level variable sampled once per world."""

    var: Name


AttributeValue = AtMinutes | Choice | Var | JsonScalar


class BlockerSpec(_Spec):
    """A hidden cause of the case's difficulty and the actions that address it."""

    description: NonEmptyStr
    weight: float = Field(gt=0)
    effective_actions: frozenset[Name] = Field(min_length=1)


class EventTemplate(_Spec):
    """One potential source event.

    probability: chance the event happens at all (ground truth).
    drop_probability: chance a happened event is not observed (observation loss).
    """

    id: Name
    source_type: NonEmptyStr
    actor: NonEmptyStr
    entity: Name = "case"
    offset_minutes: MinuteRange
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)
    when_blocker: frozenset[Name] | None = None
    probability: Probability = 1.0
    drop_probability: Probability = 0.0

    @model_validator(mode="after")
    def _check_offsets(self) -> EventTemplate:
        _check_range(self.offset_minutes, "offset_minutes")
        return self


class ScenarioFamily(_Spec):
    """Versioned, seeded generator description for one family of synthetic cases."""

    family_id: Identifier
    spec_version: int = Field(ge=1)
    case_prefix: Identifier
    description: NonEmptyStr
    source_system: NonEmptyStr
    blockers: dict[Name, BlockerSpec] = Field(min_length=1)
    variables: dict[Name, Choice] = Field(default_factory=dict)
    recording_delay_minutes: MinuteRange = (0, 0)
    templates: tuple[EventTemplate, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_references(self) -> ScenarioFamily:
        _check_range(self.recording_delay_minutes, "recording_delay_minutes")
        problems: list[str] = []
        ids = [template.id for template in self.templates]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            problems.append(f"duplicate template ids {duplicates}")
        for template in self.templates:
            unknown = sorted((template.when_blocker or frozenset()) - self.blockers.keys())
            if unknown:
                problems.append(f"template {template.id!r}: unknown blockers {unknown}")
            used = {v.var for v in template.attributes.values() if isinstance(v, Var)}
            undefined = sorted(used - self.variables.keys())
            if undefined:
                problems.append(f"template {template.id!r}: undefined variables {undefined}")
        if problems:
            raise ValueError("; ".join(problems))
        return self


def load_family(path: str | Path) -> ScenarioFamily:
    data = load_yaml_mapping(path)
    try:
        return ScenarioFamily.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid scenario family in {path}:\n{exc}") from exc


def load_families(directory: str | Path) -> tuple[ScenarioFamily, ...]:
    """Load every *.yaml family in a directory, sorted by family_id."""
    paths = sorted(Path(directory).glob("*.yaml"))
    if not paths:
        raise ConfigError(f"no scenario families found in {directory}")
    families = sorted((load_family(p) for p in paths), key=lambda f: f.family_id)
    ids = [f.family_id for f in families]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ConfigError(f"duplicate scenario family ids {duplicates}")
    return tuple(families)
