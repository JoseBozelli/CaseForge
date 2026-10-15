"""Simulated environment exposed through the engine's case, action and outcome ports."""

from __future__ import annotations

from datetime import datetime

from caseforge.events.source import SourceEvent
from caseforge.outcomes.models import OutcomeObservation
from caseforge.simulation.world import SimulatedWorld


class SimulatedEnvironment:
    """Registry of simulated worlds implementing CaseSource, ActionExecutor and OutcomeSource.

    Deliberately offers no access to ground truth: the engine holds this object, so
    evaluation code reads ground truth from the SimulatedWorld handles it created.
    """

    def __init__(self) -> None:
        self._worlds: dict[tuple[str, str], SimulatedWorld] = {}

    def register(self, world: SimulatedWorld) -> str:
        key = (world.tenant_id, world.case_id)
        existing = self._worlds.get(key)
        if existing is not None and existing is not world:
            raise ValueError(f"case {world.case_id!r} already registered for {world.tenant_id!r}")
        self._worlds[key] = world
        return world.case_id

    def source_events(
        self, tenant_id: str, case_id: str, as_of: datetime
    ) -> tuple[SourceEvent, ...]:
        return self._world(tenant_id, case_id).observable_view(as_of).events

    def execute(
        self, *, tenant_id: str, case_id: str, action_id: str, action_type: str, at: datetime
    ) -> bool:
        return self._world(tenant_id, case_id).apply_action(action_id, action_type, at)

    def observe(
        self, *, tenant_id: str, case_id: str, action_id: str, as_of: datetime
    ) -> OutcomeObservation:
        return self._world(tenant_id, case_id).outcome_for(action_id, as_of)

    def _world(self, tenant_id: str, case_id: str) -> SimulatedWorld:
        world = self._worlds.get((tenant_id, case_id))
        if world is None:
            raise KeyError(f"no simulated case {case_id!r} for tenant {tenant_id!r}")
        return world
