"""Template-driven simulation provider: seeded, deterministic synthetic case worlds."""

from __future__ import annotations

import random
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol

from caseforge.simulation.sampling import (
    SampledEvent,
    WorldContext,
    derive_seed,
    pick,
    sample_event,
    weighted,
)
from caseforge.simulation.spec import ScenarioFamily
from caseforge.simulation.world import SimulatedWorld


class SimulationProvider(Protocol):
    """Port for generators of synthetic case worlds."""

    def family_ids(self) -> tuple[str, ...]: ...

    def create(
        self, family_id: str, seed: int, *, tenant_id: str, start_at: datetime
    ) -> SimulatedWorld: ...


def derive_world_seed(family_id: str, spec_version: int, seed: int) -> int:
    """Stable per-world seed, independent of creation order."""
    return derive_seed(family_id, spec_version, seed)


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
        blocker = weighted(rng, {name: spec.weight for name, spec in family.blockers.items()})
        variables = {
            name: pick(rng, spec.choice) for name, spec in sorted(family.variables.items())
        }
        context = WorldContext(
            family=family,
            case_id=f"{family.case_prefix}-{seed:04d}",
            tenant_id=tenant_id,
            start=start,
            blocker=blocker,
            variables=variables,
        )
        initial: list[SampledEvent] = []
        for template in family.templates:
            sampled = sample_event(template, rng, context, start)
            if sampled is not None:
                initial.append(sampled)
        return SimulatedWorld(context, seed=seed, world_seed=world_seed, initial=initial)
