"""In-memory RecordStore: non-durable, same contract as the SQLite implementation."""

from __future__ import annotations

from collections.abc import Iterable

from caseforge.events.envelope import EventEnvelope
from caseforge.events.mapping import Rejection
from caseforge.persistence.codec import event_sha256, rejection_key
from caseforge.persistence.ports import IntakeResult, RecordConflictError
from caseforge.provenance.manifest import RunManifest


class InMemoryRecordStore:
    """RecordStore for tests and replay; contents are lost when the object is discarded."""

    def __init__(self) -> None:
        self._manifests: dict[str, RunManifest] = {}
        self._events: dict[tuple[str, str], tuple[str, EventEnvelope]] = {}
        self._rejections: list[Rejection] = []
        self._rejection_keys: set[tuple[str, str, str, int, str]] = set()

    def __enter__(self) -> InMemoryRecordStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Nothing to release."""

    def save_manifest(self, manifest: RunManifest) -> None:
        existing = self._manifests.get(manifest.run_id)
        if existing is None:
            self._manifests[manifest.run_id] = manifest
        elif existing.sha256() != manifest.sha256():
            raise RecordConflictError(
                f"run {manifest.run_id!r} already recorded with different content"
            )

    def get_manifest(self, run_id: str) -> RunManifest | None:
        return self._manifests.get(run_id)

    def append_events(self, events: Iterable[EventEnvelope]) -> IntakeResult:
        inserted: list[str] = []
        duplicates: list[str] = []
        conflicts: list[str] = []
        for event in events:
            key = (event.tenant_id, event.event_id)
            digest = event_sha256(event)
            existing = self._events.get(key)
            if existing is None:
                self._events[key] = (digest, event)
                inserted.append(event.event_id)
            elif existing[0] == digest:
                duplicates.append(event.event_id)
            else:
                conflicts.append(event.event_id)
        return IntakeResult(tuple(inserted), tuple(duplicates), tuple(conflicts))

    def events_for_case(self, tenant_id: str, case_id: str) -> tuple[EventEnvelope, ...]:
        matching = [
            event
            for (tenant, _), (_, event) in self._events.items()
            if tenant == tenant_id and event.case_id == case_id
        ]
        return tuple(sorted(matching, key=lambda e: (e.recorded_at, e.event_id)))

    def save_rejections(self, rejections: Iterable[Rejection]) -> int:
        count = 0
        for rejection in rejections:
            key = rejection_key(rejection)
            if key not in self._rejection_keys:
                self._rejection_keys.add(key)
                self._rejections.append(rejection)
                count += 1
        return count

    def list_rejections(self, source_system: str | None = None) -> tuple[Rejection, ...]:
        return tuple(
            r for r in self._rejections if source_system is None or r.source_system == source_system
        )
