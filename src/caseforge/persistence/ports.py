"""RecordStore port and shared result types."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from caseforge.events.envelope import EventEnvelope
from caseforge.events.mapping import Rejection
from caseforge.provenance.manifest import RunManifest


class RecordStoreError(Exception):
    """Raised for storage failures and incompatible storage state."""


class RecordConflictError(RecordStoreError):
    """Raised when a record id already exists with different content."""


@dataclass(frozen=True)
class IntakeResult:
    """Per-event outcome of an append: new, identical repeat, or same id with new content."""

    inserted: tuple[str, ...]
    duplicates: tuple[str, ...]
    conflicts: tuple[str, ...]


class RecordStore(Protocol):
    """Durable or in-memory storage for manifests, canonical events and rejections.

    Events are keyed by (tenant_id, event_id). Identical repeats are ignored;
    a repeat with different content is reported as a conflict and never overwrites.
    """

    def save_manifest(self, manifest: RunManifest) -> None: ...

    def get_manifest(self, run_id: str) -> RunManifest | None: ...

    def append_events(self, events: Iterable[EventEnvelope]) -> IntakeResult: ...

    def events_for_case(self, tenant_id: str, case_id: str) -> tuple[EventEnvelope, ...]: ...

    def save_rejections(self, rejections: Iterable[Rejection]) -> int: ...

    def list_rejections(self, source_system: str | None = None) -> tuple[Rejection, ...]: ...

    def close(self) -> None: ...
