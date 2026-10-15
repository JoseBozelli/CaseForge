"""Deterministic sampling helpers and event construction shared by the simulator.

Only random.Random.random() is used, because its output sequence for a given seed
is stable across Python versions; integer, choice and weighted draws are derived
from it here instead of from version-dependent helpers.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from caseforge.common.hashing import sha256_hex
from caseforge.events.source import SourceEvent
from caseforge.simulation.spec import (
    AtMinutes,
    AttributeValue,
    Choice,
    EventTemplate,
    ScenarioFamily,
    Var,
)


def derive_seed(*parts: Any) -> int:
    """Stable 64-bit seed from JSON-compatible parts."""
    return int(sha256_hex(list(parts))[:16], 16)


def randint(rng: random.Random, low: int, high: int) -> int:
    return low + int(rng.random() * (high - low + 1))


def pick(rng: random.Random, options: Sequence[Any]) -> Any:
    return options[int(rng.random() * len(options))]


def weighted(rng: random.Random, weights: Mapping[str, float]) -> str:
    names = sorted(weights)
    threshold = rng.random() * sum(weights[name] for name in names)
    cumulative = 0.0
    for name in names:
        cumulative += weights[name]
        if threshold < cumulative:
            return name
    return names[-1]


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_value(
    value: AttributeValue, rng: random.Random, start: datetime, variables: Mapping[str, Any]
) -> Any:
    if isinstance(value, AtMinutes):
        return iso(start + timedelta(minutes=value.at_minutes))
    if isinstance(value, Choice):
        return pick(rng, value.choice)
    if isinstance(value, Var):
        return variables[value.var]
    return value


@dataclass(frozen=True)
class WorldContext:
    """Fixed facts of one world, shared by initial and post-action event sampling."""

    family: ScenarioFamily
    case_id: str
    tenant_id: str
    start: datetime
    blocker: str
    variables: Mapping[str, Any]


@dataclass(frozen=True)
class SampledEvent:
    event: SourceEvent
    dropped: bool


def sample_event(
    template: EventTemplate, rng: random.Random, context: WorldContext, base_time: datetime
) -> SampledEvent | None:
    """Sample one template; None when it does not apply or does not happen."""
    if template.when_blocker is not None and context.blocker not in template.when_blocker:
        return None
    if rng.random() >= template.probability:
        return None
    family = context.family
    occurred_at = base_time + timedelta(minutes=randint(rng, *template.offset_minutes))
    delay = randint(rng, *family.recording_delay_minutes)
    attributes = {
        key: resolve_value(template.attributes[key], rng, context.start, context.variables)
        for key in sorted(template.attributes)
    }
    case_id = context.case_id
    event = SourceEvent(
        source_system=family.source_system,
        source_event_id=f"{case_id}-{template.id}",
        source_type=template.source_type,
        tenant_id=context.tenant_id,
        entity_id=case_id if template.entity == "case" else f"{case_id}-{template.entity}",
        case_id=case_id,
        actor=template.actor,
        occurred_at=occurred_at,
        recorded_at=occurred_at + timedelta(minutes=delay),
        attributes=attributes,
    )
    return SampledEvent(event=event, dropped=rng.random() < template.drop_probability)
