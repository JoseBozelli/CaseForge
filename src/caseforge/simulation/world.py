"""Simulated worlds and their model-visible views."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from caseforge.events.source import SourceEvent
from caseforge.simulation.ground_truth import GroundTruth


@dataclass(frozen=True)
class ObservableWorld:
    """Model-visible snapshot of a simulated case: observed source events only."""

    case_id: str
    tenant_id: str
    source_system: str
    events: tuple[SourceEvent, ...]

    def events_until(self, as_of: datetime) -> tuple[SourceEvent, ...]:
        """Events already recorded at as_of, in recording order."""
        return tuple(event for event in self.events if event.recorded_at <= as_of)


class SimulatedWorld:
    """One synthetic case: observed events plus hidden ground truth."""

    def __init__(
        self,
        *,
        case_id: str,
        tenant_id: str,
        source_system: str,
        observed: Iterable[SourceEvent],
        truth: GroundTruth,
    ) -> None:
        self._case_id = case_id
        self._tenant_id = tenant_id
        self._source_system = source_system
        self._observed = list(observed)
        self._truth = truth

    def observable_view(self) -> ObservableWorld:
        """Return a snapshot that contains no ground-truth information."""
        events = sorted(self._observed, key=lambda e: (e.recorded_at, e.source_event_id))
        return ObservableWorld(
            case_id=self._case_id,
            tenant_id=self._tenant_id,
            source_system=self._source_system,
            events=tuple(events),
        )

    def ground_truth(self) -> GroundTruth:
        """Hidden facts for evaluation only; never pass to agent-side code."""
        return self._truth
