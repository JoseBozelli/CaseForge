"""Simulated environment exposed through the engine's case, action and outcome ports."""

from __future__ import annotations

from datetime import UTC, datetime

from caseforge.adapters.simulation_log import LoggedCase, SimulationLogError, SqliteSimulationLog
from caseforge.events.source import SourceEvent
from caseforge.outcomes.models import OutcomeObservation
from caseforge.simulation.provider import SimulationProvider
from caseforge.simulation.world import SimulatedWorld


class SimulatedEnvironment:
    """Simulated worlds behind CaseSource, ActionExecutor and OutcomeSource.

    With a log, cases and applied actions are durable and worlds are rebuilt
    deterministically by restore(). Deliberately offers no access to ground truth:
    the engine holds this object; evaluation reads truth from the world handles.
    """

    supports_idempotency_keys = True  # SimulatedWorld.apply_action ignores repeated ids

    def __init__(
        self, provider: SimulationProvider, log: SqliteSimulationLog | None = None
    ) -> None:
        self._provider = provider
        self._log = log
        self._worlds: dict[tuple[str, str], SimulatedWorld] = {}

    def restore(self) -> int:
        """Rebuild every logged world and re-apply its logged actions in order."""
        if self._log is None:
            return 0
        for case in self._log.cases():
            world = self._provider.create(
                case.family_id, case.seed, tenant_id=case.tenant_id, start_at=case.start_at
            )
            for action in self._log.actions(case.tenant_id, case.case_id):
                world.apply_action(action.action_id, action.action_type, action.at)
            self._worlds[(case.tenant_id, case.case_id)] = world
        return len(self._worlds)

    def open_case(
        self, family_id: str, seed: int, *, tenant_id: str, start_at: datetime
    ) -> SimulatedWorld:
        """Create (or return the existing) world; differing parameters are refused."""
        world = self._provider.create(family_id, seed, tenant_id=tenant_id, start_at=start_at)
        key = (tenant_id, world.case_id)
        existing = self._worlds.get(key)
        if existing is not None:
            if (existing.family_id, existing.seed, existing.start_at) != (
                family_id,
                seed,
                start_at.astimezone(UTC),
            ):
                raise SimulationLogError(
                    f"case {world.case_id!r} already registered with different parameters"
                )
            return existing
        if self._log is not None:
            self._log.register_case(LoggedCase(tenant_id, world.case_id, family_id, seed, start_at))
        self._worlds[key] = world
        return world

    def source_events(
        self, tenant_id: str, case_id: str, as_of: datetime
    ) -> tuple[SourceEvent, ...]:
        return self._world(tenant_id, case_id).observable_view(as_of).events

    def execute(
        self, *, tenant_id: str, case_id: str, action_id: str, action_type: str, at: datetime
    ) -> bool:
        """Apply, then log. A crash in between loses the action, like an external system
        losing an unsaved write; the engine's ledger resends and the world applies it once."""
        applied = self._world(tenant_id, case_id).apply_action(action_id, action_type, at)
        if applied and self._log is not None:
            self._log.append_action(tenant_id, case_id, action_id, action_type, at)
        return applied

    def observe(
        self, *, tenant_id: str, case_id: str, action_id: str, as_of: datetime
    ) -> OutcomeObservation:
        return self._world(tenant_id, case_id).outcome_for(action_id, as_of)

    def _world(self, tenant_id: str, case_id: str) -> SimulatedWorld:
        world = self._worlds.get((tenant_id, case_id))
        if world is None:
            raise KeyError(f"no simulated case {case_id!r} for tenant {tenant_id!r}")
        return world
