"""Governance records."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from caseforge.events.envelope import NonEmptyStr, UtcDatetime


class AuditEntry(BaseModel):
    """One governance decision or operation. The audit log is append-only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int | None = None
    at: UtcDatetime
    actor: NonEmptyStr
    action: NonEmptyStr
    target: NonEmptyStr
    outcome: Literal["allowed", "denied", "recorded"]
    detail: dict[str, JsonValue] = Field(default_factory=dict)


class SwitchState(BaseModel):
    """Current position of a governance switch and who last changed it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: NonEmptyStr
    engaged: bool
    actor: NonEmptyStr
    reason: str
    changed_at: UtcDatetime


class RunUsage(BaseModel):
    """Spend counted for one run so far."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: NonEmptyStr
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    tool_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class BudgetDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    reason: str | None = None
    usage: RunUsage


class BreakerState(BaseModel):
    """Circuit breaker for one resource (reasoner, executor or tool:<name>)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resource: NonEmptyStr
    state: Literal["closed", "open", "half_open"]
    failures: int = 0
    opened_at: UtcDatetime | None = None
    updated_at: UtcDatetime
