"""RecordStore port and shared result types."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from caseforge.events.envelope import EventEnvelope
from caseforge.events.mapping import Rejection
from caseforge.persistence.errors import LedgerTransitionError as LedgerTransitionError
from caseforge.persistence.errors import RecordConflictError as RecordConflictError
from caseforge.persistence.errors import RecordStoreError as RecordStoreError
from caseforge.persistence.records import (
    ActionLedgerEntry,
    ApprovalRecord,
    DecisionRecord,
    DecisionSave,
    EpisodeRecord,
    LedgerStatus,
)
from caseforge.provenance.manifest import RunManifest
from caseforge.reasoning.models import LlmCallRecord
from caseforge.tools.models import ToolInvocationRecord


@dataclass(frozen=True)
class IntakeResult:
    """Per-event outcome of an append: new, identical repeat, or same id with new content."""

    inserted: tuple[str, ...]
    duplicates: tuple[str, ...]
    conflicts: tuple[str, ...]


class RecordStore(Protocol):
    """Storage for manifests, events, rejections, call records, decisions and the ledger.

    Events are keyed by (tenant_id, event_id): identical repeats are ignored and a
    repeat with different content is a conflict that never overwrites. Model and tool
    call records are append-only. The first committed decision per run wins. Ledger
    entries change status only through validated transitions.
    """

    def save_manifest(self, manifest: RunManifest) -> None: ...

    def get_manifest(self, run_id: str) -> RunManifest | None: ...

    def append_events(self, events: Iterable[EventEnvelope]) -> IntakeResult: ...

    def events_for_case(self, tenant_id: str, case_id: str) -> tuple[EventEnvelope, ...]: ...

    def save_rejections(self, rejections: Iterable[Rejection]) -> int: ...

    def list_rejections(self, source_system: str | None = None) -> tuple[Rejection, ...]: ...

    def save_llm_calls(self, records: Iterable[LlmCallRecord]) -> int: ...

    def llm_calls_for_run(self, run_id: str) -> tuple[LlmCallRecord, ...]: ...

    def save_tool_invocations(self, records: Iterable[ToolInvocationRecord]) -> int: ...

    def tool_invocations_for_run(self, run_id: str) -> tuple[ToolInvocationRecord, ...]: ...

    def save_decision(self, record: DecisionRecord) -> DecisionSave: ...

    def get_decision(self, run_id: str) -> DecisionRecord | None: ...

    def begin_action(self, entry: ActionLedgerEntry) -> ActionLedgerEntry: ...

    def transition_action(
        self,
        idempotency_key: str,
        status: LedgerStatus,
        *,
        at: datetime,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> ActionLedgerEntry: ...

    def get_action(self, idempotency_key: str) -> ActionLedgerEntry | None: ...

    def save_approval(self, record: ApprovalRecord) -> bool: ...

    def approvals_for_run(self, run_id: str) -> tuple[ApprovalRecord, ...]: ...

    def save_episode(self, record: EpisodeRecord) -> None: ...

    def episodes_for_tenant(self, tenant_id: str) -> tuple[EpisodeRecord, ...]: ...

    def close(self) -> None: ...
