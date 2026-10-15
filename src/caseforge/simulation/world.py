"""Simulated worlds: observed events, operator actions, outcomes and hidden truth."""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from caseforge.events.source import SourceEvent
from caseforge.outcomes.models import OutcomeObservation, OutcomeStatus
from caseforge.simulation.ground_truth import ActionTruth, GroundTruth
from caseforge.simulation.sampling import (
    SampledEvent,
    WorldContext,
    derive_seed,
    randint,
    sample_event,
)
from caseforge.simulation.spec import Dynamics


def _utc(moment: datetime, label: str) -> datetime:
    if moment.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return moment.astimezone(UTC)


@dataclass(frozen=True)
class ObservableWorld:
    """Model-visible snapshot of a case: events recorded at or before as_of only."""

    case_id: str
    tenant_id: str
    source_system: str
    as_of: datetime
    events: tuple[SourceEvent, ...]

    def events_until(self, as_of: datetime) -> tuple[SourceEvent, ...]:
        """Events already recorded at as_of, in recording order."""
        return tuple(event for event in self.events if event.recorded_at <= as_of)


class SimulatedWorld:
    """One synthetic case: observed events, applied actions and hidden ground truth."""

    def __init__(
        self,
        context: WorldContext,
        *,
        seed: int,
        world_seed: int,
        initial: Iterable[SampledEvent],
    ) -> None:
        self._ctx = context
        self._seed = seed
        self._world_seed = world_seed
        self._observed: list[SourceEvent] = []
        self._occurred: list[str] = []
        self._dropped: list[str] = []
        self._actions: dict[str, ActionTruth] = {}
        self._resolved_by: str | None = None
        for sampled in initial:
            self._record(sampled)

    @property
    def case_id(self) -> str:
        return self._ctx.case_id

    def observable_view(self, as_of: datetime) -> ObservableWorld:
        """Snapshot of events recorded by as_of; contains no ground-truth information."""
        as_of = _utc(as_of, "as_of")
        visible = (e for e in self._observed if e.recorded_at <= as_of)
        events = sorted(visible, key=lambda e: (e.recorded_at, e.source_event_id))
        return ObservableWorld(
            case_id=self._ctx.case_id,
            tenant_id=self._ctx.tenant_id,
            source_system=self._ctx.family.source_system,
            as_of=as_of,
            events=tuple(events),
        )

    def apply_action(self, action_id: str, action_type: str, at: datetime) -> bool:
        """Apply an operator action; False when this action_id was already applied.

        The action_id acts as an idempotency key: a repeat with identical content is
        ignored, and a repeat with different content is rejected.
        """
        dynamics = self._dynamics()
        at = _utc(at, "at")
        if at < self._ctx.start:
            raise ValueError("action precedes world start")
        existing = self._actions.get(action_id)
        if existing is not None:
            if (existing.action_type, existing.acted_at) != (action_type, at):
                raise ValueError(f"action_id {action_id!r} reused with different content")
            return False

        rng = random.Random(derive_seed(self._world_seed, action_id, action_type))
        probability = dynamics.actions.get(action_type, {}).get(self._ctx.blocker, 0.0)
        already_resolved = self._resolved_by is not None
        resolve_draw = rng.random()
        observable_draw = rng.random()
        delay = randint(rng, *dynamics.resolution_delay_minutes)
        resolved = not already_resolved and resolve_draw < probability
        resolution_at = at + timedelta(minutes=delay) if resolved else None

        self._actions[action_id] = ActionTruth(
            action_id=action_id,
            action_type=action_type,
            acted_at=at,
            resolve_probability=probability,
            already_resolved=already_resolved,
            resolved=resolved,
            resolution_at=resolution_at,
            outcome_observable=observable_draw >= dynamics.unobservable_probability,
        )
        if resolution_at is not None:
            self._resolved_by = action_id
            for template in dynamics.resolution_events:
                sampled = sample_event(template, rng, self._ctx, resolution_at)
                if sampled is not None:
                    self._record(sampled)
        return True

    def outcome_for(self, action_id: str, as_of: datetime) -> OutcomeObservation:
        """What is observable about an action's outcome at as_of.

        Success requires that this action resolved the case within the horizon.
        """
        dynamics = self._dynamics()
        truth = self._actions.get(action_id)
        if truth is None:
            raise ValueError(f"unknown action {action_id!r}")
        as_of = _utc(as_of, "as_of")
        if as_of < truth.acted_at:
            raise ValueError("as_of precedes the action")
        horizon_end = truth.acted_at + timedelta(minutes=dynamics.horizon_minutes)
        resolution_at = truth.resolution_at
        succeeded = resolution_at is not None and resolution_at <= horizon_end

        status, observed_at = OutcomeStatus.PENDING, None
        if not truth.outcome_observable:
            if as_of >= horizon_end:
                status, observed_at = OutcomeStatus.UNOBSERVABLE, horizon_end
        elif succeeded and resolution_at is not None and resolution_at <= as_of:
            status, observed_at = OutcomeStatus.SUCCESS, resolution_at
        elif as_of >= horizon_end:
            status, observed_at = OutcomeStatus.FAILURE, horizon_end

        return OutcomeObservation(
            action_id=truth.action_id,
            action_type=truth.action_type,
            status=status,
            acted_at=truth.acted_at,
            horizon_end=horizon_end,
            observed_at=observed_at,
        )

    def ground_truth(self) -> GroundTruth:
        """Hidden facts for evaluation only; never pass to agent-side code."""
        family = self._ctx.family
        blocker = self._ctx.blocker
        return GroundTruth(
            family_id=family.family_id,
            spec_version=family.spec_version,
            seed=self._seed,
            world_seed=self._world_seed,
            case_id=self._ctx.case_id,
            blocker=blocker,
            effective_actions=tuple(sorted(family.blockers[blocker].effective_actions)),
            variables=dict(self._ctx.variables),
            occurred_event_ids=tuple(self._occurred),
            dropped_event_ids=tuple(self._dropped),
            actions=tuple(sorted(self._actions.values(), key=lambda a: (a.acted_at, a.action_id))),
            resolved_by=self._resolved_by,
        )

    def _dynamics(self) -> Dynamics:
        dynamics = self._ctx.family.dynamics
        if dynamics is None:
            raise ValueError(f"scenario family {self._ctx.family.family_id!r} defines no dynamics")
        return dynamics

    def _record(self, sampled: SampledEvent) -> None:
        self._occurred.append(sampled.event.source_event_id)
        if sampled.dropped:
            self._dropped.append(sampled.event.source_event_id)
        else:
            self._observed.append(sampled.event)
