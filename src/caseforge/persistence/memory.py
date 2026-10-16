"""In-memory RecordStore: non-durable, same contract as the SQLite implementation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel

from caseforge.events.envelope import EventEnvelope
from caseforge.events.mapping import Rejection
from caseforge.persistence.codec import encode_model, event_sha256, rejection_key
from caseforge.persistence.errors import (
    LedgerTransitionError,
    RecordConflictError,
    RecordStoreError,
)
from caseforge.persistence.ports import IntakeResult
from caseforge.persistence.records import (
    ActionLedgerEntry,
    DecisionRecord,
    DecisionSave,
    LedgerStatus,
    transition,
)
from caseforge.provenance.manifest import RunManifest
from caseforge.reasoning.models import LlmCallRecord
from caseforge.tools.models import ToolInvocationRecord

R = TypeVar("R", bound=BaseModel)


def _append_unique(
    rows: list[R], keys: set[tuple[str, str]], items: Iterable[R], identity: Callable[[R], str]
) -> int:
    count = 0
    for item in items:
        key = (identity(item), encode_model(item)[1])
        if key not in keys:
            keys.add(key)
            rows.append(item)
            count += 1
    return count


class InMemoryRecordStore:
    """RecordStore for tests and replay; contents are lost when the object is discarded."""

    def __init__(self) -> None:
        self._manifests: dict[str, RunManifest] = {}
        self._events: dict[tuple[str, str], tuple[str, EventEnvelope]] = {}
        self._rejections: list[Rejection] = []
        self._rejection_keys: set[tuple[str, str, str, int, str]] = set()
        self._llm_calls: list[LlmCallRecord] = []
        self._llm_keys: set[tuple[str, str]] = set()
        self._tool_calls: list[ToolInvocationRecord] = []
        self._tool_keys: set[tuple[str, str]] = set()
        self._decisions: dict[str, DecisionRecord] = {}
        self._ledger: dict[str, ActionLedgerEntry] = {}

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

    def save_llm_calls(self, records: Iterable[LlmCallRecord]) -> int:
        return _append_unique(self._llm_calls, self._llm_keys, records, lambda r: r.call_id)

    def llm_calls_for_run(self, run_id: str) -> tuple[LlmCallRecord, ...]:
        return tuple(r for r in self._llm_calls if r.run_id == run_id)

    def save_tool_invocations(self, records: Iterable[ToolInvocationRecord]) -> int:
        return _append_unique(self._tool_calls, self._tool_keys, records, lambda r: r.invocation_id)

    def tool_invocations_for_run(self, run_id: str) -> tuple[ToolInvocationRecord, ...]:
        return tuple(r for r in self._tool_calls if r.run_id == run_id)

    def save_decision(self, record: DecisionRecord) -> DecisionSave:
        existing = self._decisions.get(record.run_id)
        if existing is None:
            self._decisions[record.run_id] = record
            return DecisionSave(record, "inserted")
        same = existing.material_sha256() == record.material_sha256()
        return DecisionSave(existing, "duplicate" if same else "conflict")

    def get_decision(self, run_id: str) -> DecisionRecord | None:
        return self._decisions.get(run_id)

    def begin_action(self, entry: ActionLedgerEntry) -> ActionLedgerEntry:
        if entry.status != LedgerStatus.INTENT:
            raise LedgerTransitionError("a ledger entry must begin in the intent status")
        return self._ledger.setdefault(entry.idempotency_key, entry)

    def transition_action(
        self,
        idempotency_key: str,
        status: LedgerStatus,
        *,
        at: datetime,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> ActionLedgerEntry:
        current = self._ledger.get(idempotency_key)
        if current is None:
            raise RecordStoreError(f"unknown action {idempotency_key!r}")
        updated = transition(current, status, at=at, result=result, error=error)
        self._ledger[idempotency_key] = updated
        return updated

    def get_action(self, idempotency_key: str) -> ActionLedgerEntry | None:
        return self._ledger.get(idempotency_key)
