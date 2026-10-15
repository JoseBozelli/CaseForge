"""Template-driven simulation provider: seeded, deterministic synthetic case worlds.

Randomness uses random.Random.random() only, whose output sequence for a given
seed is stable across Python versions; integer, choice and weighted draws are
derived from it here rather than from version-dependent helpers.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from caseforge.common.hashing import sha256_hex
from caseforge.events.source import SourceEvent
from caseforge.simulation.ground_truth import GroundTruth
from caseforge.simulation.spec import AtMinutes, AttributeValue, Choice, ScenarioFamily, Var
from caseforge.simulation.world import SimulatedWorld


class SimulationProvider(Protocol):
    """Port for generators of synthetic case worlds."""

    def family_ids(self) -> tuple[str, ...]: ...

    def create(
        self, family_id: str, seed: int, *, tenant_id: str, start_at: datetime
    ) -> SimulatedWorld: ...


def derive_world_seed(family_id: str, spec_version: int, seed: int) -> int:
    """Stable per-world seed, independent of creation order."""
    return int(sha256_hex([family_id, spec_version, seed])[:16], 16)


def _randint(rng: random.Random, low: int, high: int) -> int:
    return low + int(rng.random() * (high - low + 1))


def _pick(rng: random.Random, options: Sequence[Any]) -> Any:
    return options[int(rng.random() * len(options))]


def _weighted(rng: random.Random, weights: Mapping[str, float]) -> str:
    names = sorted(weights)
    threshold = rng.random() * sum(weights[name] for name in names)
    cumulative = 0.0
    for name in names:
        cumulative += weights[name]
        if threshold < cumulative:
            return name
    return names[-1]


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve(
    value: AttributeValue, rng: random.Random, start: datetime, variables: Mapping[str, Any]
) -> Any:
    if isinstance(value, AtMinutes):
        return _iso(start + timedelta(minutes=value.at_minutes))
    if isinstance(value, Choice):
        return _pick(rng, value.choice)
    if isinstance(value, Var):
        return variables[value.var]
    return value


class TemplateSimulationProvider:
    """Builds worlds from ScenarioFamily templates."""

    def __init__(self, families: Iterable[ScenarioFamily]) -> None:
        self._families: dict[str, ScenarioFamily] = {}
        for family in families:
            if family.family_id in self._families:
                raise ValueError(f"duplicate scenario family {family.family_id!r}")
            self._families[family.family_id] = family

    def family_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._families))

    def create(
        self, family_id: str, seed: int, *, tenant_id: str, start_at: datetime
    ) -> SimulatedWorld:
        family = self._families.get(family_id)
        if family is None:
            raise ValueError(f"unknown scenario family {family_id!r}")
        if seed < 0:
            raise ValueError("seed must be non-negative")
        if start_at.tzinfo is None:
            raise ValueError("start_at must be timezone-aware")

        start = start_at.astimezone(UTC)
        world_seed = derive_world_seed(family.family_id, family.spec_version, seed)
        rng = random.Random(world_seed)
        case_id = f"{family.case_prefix}-{seed:04d}"
        blocker = _weighted(rng, {name: spec.weight for name, spec in family.blockers.items()})
        variables = {
            name: _pick(rng, spec.choice) for name, spec in sorted(family.variables.items())
        }

        observed: list[SourceEvent] = []
        occurred_ids: list[str] = []
        dropped_ids: list[str] = []
        for template in family.templates:
            if template.when_blocker is not None and blocker not in template.when_blocker:
                continue
            if rng.random() >= template.probability:
                continue
            occurred_at = start + timedelta(minutes=_randint(rng, *template.offset_minutes))
            delay = _randint(rng, *family.recording_delay_minutes)
            attributes = {
                key: _resolve(template.attributes[key], rng, start, variables)
                for key in sorted(template.attributes)
            }
            event = SourceEvent(
                source_system=family.source_system,
                source_event_id=f"{case_id}-{template.id}",
                source_type=template.source_type,
                tenant_id=tenant_id,
                entity_id=case_id if template.entity == "case" else f"{case_id}-{template.entity}",
                case_id=case_id,
                actor=template.actor,
                occurred_at=occurred_at,
                recorded_at=occurred_at + timedelta(minutes=delay),
                attributes=attributes,
            )
            occurred_ids.append(event.source_event_id)
            if rng.random() < template.drop_probability:
                dropped_ids.append(event.source_event_id)
            else:
                observed.append(event)

        truth = GroundTruth(
            family_id=family.family_id,
            spec_version=family.spec_version,
            seed=seed,
            world_seed=world_seed,
            case_id=case_id,
            blocker=blocker,
            effective_actions=tuple(sorted(family.blockers[blocker].effective_actions)),
            variables=variables,
            occurred_event_ids=tuple(occurred_ids),
            dropped_event_ids=tuple(dropped_ids),
        )
        return SimulatedWorld(
            case_id=case_id,
            tenant_id=tenant_id,
            source_system=family.source_system,
            observed=observed,
            truth=truth,
        )
