"""Durable run records: committed decisions and the action ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from caseforge.common.hashing import sha256_hex
from caseforge.events.envelope import NonEmptyStr, UtcDatetime
from caseforge.events.vocabulary import Name
from caseforge.persistence.errors import LedgerTransitionError


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DecisionRecord(_Frozen):
    """The decision a run committed to. The first committed decision per run wins."""

    run_id: NonEmptyStr
    case_id: NonEmptyStr
    tenant_id: NonEmptyStr
    decision_id: NonEmptyStr
    source: Literal["triage", "supervisor", "escalation"]
    action_type: Name
    rule_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    reason: str | None = None
    decided_at: UtcDatetime

    def material_sha256(self) -> str:
        """Hash of the decision's content, excluding when it was made."""
        return sha256_hex(self.model_dump(mode="json", exclude={"decided_at"}))


@dataclass(frozen=True)
class DecisionSave:
    stored: DecisionRecord
    status: Literal["inserted", "duplicate", "conflict"]


class LedgerStatus(StrEnum):
    INTENT = "intent"
    DISPATCHED = "dispatched"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


_ALLOWED: dict[LedgerStatus, frozenset[LedgerStatus]] = {
    LedgerStatus.INTENT: frozenset({LedgerStatus.DISPATCHED, LedgerStatus.FAILED}),
    LedgerStatus.DISPATCHED: frozenset(
        {LedgerStatus.SUCCEEDED, LedgerStatus.FAILED, LedgerStatus.UNKNOWN}
    ),
    LedgerStatus.UNKNOWN: frozenset({LedgerStatus.SUCCEEDED, LedgerStatus.FAILED}),
    LedgerStatus.FAILED: frozenset({LedgerStatus.DISPATCHED}),
    LedgerStatus.SUCCEEDED: frozenset(),
}


class ActionLedgerEntry(_Frozen):
    """One external action, tracked from intent to a known or unknown result.

    dispatched means the action may have been sent; unknown means its result could
    not be determined and must be reconciled, never blindly retried.
    """

    idempotency_key: NonEmptyStr
    run_id: NonEmptyStr
    case_id: NonEmptyStr
    tenant_id: NonEmptyStr
    action_type: Name
    status: LedgerStatus = LedgerStatus.INTENT
    attempts: int = Field(default=0, ge=0)
    result: dict[str, JsonValue] | None = None
    error: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


def transition(
    entry: ActionLedgerEntry,
    status: LedgerStatus,
    *,
    at: datetime,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> ActionLedgerEntry:
    """Return the entry after a validated status change; dispatching counts an attempt."""
    if status not in _ALLOWED[entry.status]:
        raise LedgerTransitionError(
            f"{entry.idempotency_key}: {entry.status} -> {status} is not allowed"
        )
    data = entry.model_dump()
    data.update(
        status=status,
        attempts=entry.attempts + (1 if status == LedgerStatus.DISPATCHED else 0),
        result=result if result is not None else entry.result,
        error=error,
        updated_at=at,
    )
    return ActionLedgerEntry.model_validate(data)


class ApprovalRecord(_Frozen):
    """A person's answer to an approval request. Append-only."""

    run_id: NonEmptyStr
    case_id: NonEmptyStr
    tenant_id: NonEmptyStr
    action_type: Name
    decision: Literal["approved", "rejected"]
    actor: NonEmptyStr
    note: str | None = Field(default=None, max_length=500)
    decided_at: UtcDatetime
