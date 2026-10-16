"""ControlPlane: decides and records governed operations.

Agents never receive this object. Operator identities are supplied by the caller and
are not authenticated here (simulated identity); roles and permissions come from
trusted configuration.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from caseforge.governance.guards import EmergencyStopEngaged
from caseforge.governance.models import (
    AuditEntry,
    BreakerState,
    BudgetDecision,
    RunUsage,
    SwitchState,
)
from caseforge.governance.permissions import EMERGENCY_STOP, MANAGE_BREAKERS, PERMISSIONS
from caseforge.governance.store import GovernanceStore
from caseforge.reasoning.models import TokenUsage
from caseforge.settings.models import GovernanceSettings, ModelPricing


class PermissionDenied(Exception):
    """Raised when an operator lacks the permission for a governed operation."""


STOP_SWITCH = "emergency_stop"


class ControlPlane:
    def __init__(
        self,
        store: GovernanceStore,
        settings: GovernanceSettings,
        *,
        clock: Callable[[], datetime],
        pricing: ModelPricing | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        self._clock = clock
        self._pricing = pricing or ModelPricing()

    def roles_of(self, actor: str) -> frozenset[str]:
        return self._settings.operators.get(actor, frozenset())

    def is_allowed(self, actor: str, permission: str) -> bool:
        if permission not in PERMISSIONS:
            raise ValueError(f"unknown permission {permission!r}")
        return any(permission in self._settings.roles[role] for role in self.roles_of(actor))

    def authorize(
        self,
        actor: str,
        permission: str,
        *,
        target: str,
        detail: Mapping[str, Any] | None = None,
    ) -> AuditEntry:
        """Decide and record; every decision, allowed or denied, is audited."""
        allowed = self.is_allowed(actor, permission)
        return self._store.append_audit(
            AuditEntry(
                at=self._clock(),
                actor=actor,
                action=permission,
                target=target,
                outcome="allowed" if allowed else "denied",
                detail=dict(detail or {}),
            )
        )

    def require(
        self,
        actor: str,
        permission: str,
        *,
        target: str,
        detail: Mapping[str, Any] | None = None,
    ) -> AuditEntry:
        entry = self.authorize(actor, permission, target=target, detail=detail)
        if entry.outcome != "allowed":
            raise PermissionDenied(f"{actor!r} lacks {permission!r} for {target!r}")
        return entry

    def record(
        self,
        actor: str,
        action: str,
        *,
        target: str,
        detail: Mapping[str, Any] | None = None,
    ) -> AuditEntry:
        """Audit a governed operation that was carried out."""
        return self._store.append_audit(
            AuditEntry(
                at=self._clock(),
                actor=actor,
                action=action,
                target=target,
                outcome="recorded",
                detail=dict(detail or {}),
            )
        )

    def audit_entries(
        self, *, action: str | None = None, target: str | None = None
    ) -> tuple[AuditEntry, ...]:
        return self._store.audit_entries(action=action, target=target)

    # emergency stop

    def engage_emergency_stop(self, actor: str, reason: str) -> SwitchState:
        return self._set_stop(actor, engaged=True, reason=reason)

    def release_emergency_stop(self, actor: str, reason: str = "released") -> SwitchState:
        return self._set_stop(actor, engaged=False, reason=reason)

    def emergency_stop(self) -> SwitchState | None:
        return self._store.get_switch(STOP_SWITCH)

    def check(self, boundary: str) -> None:
        """Raise EmergencyStopEngaged if the stop is engaged. Read fresh on every call."""
        state = self._store.get_switch(STOP_SWITCH)
        if state is not None and state.engaged:
            raise EmergencyStopEngaged(
                f"emergency stop engaged by {state.actor} ({state.reason}) at {boundary}"
            )

    def _set_stop(self, actor: str, *, engaged: bool, reason: str) -> SwitchState:
        detail = {"engaged": engaged, "reason": reason}
        self.require(actor, EMERGENCY_STOP, target=STOP_SWITCH, detail=detail)
        state = SwitchState(
            name=STOP_SWITCH,
            engaged=engaged,
            actor=actor,
            reason=reason,
            changed_at=self._clock(),
        )
        self._store.set_switch(state)
        action = "emergency_stop.engaged" if engaged else "emergency_stop.released"
        self.record(actor, action, target=STOP_SWITCH, detail=detail)
        return state

    # per-run budgets

    def reserve_llm_call(self, run_id: str) -> BudgetDecision:
        return self._audited(
            run_id, "model", self._store.reserve_llm_call(run_id, self._settings.budgets)
        )

    def record_llm_usage(self, run_id: str, usage: TokenUsage) -> RunUsage:
        cost = (
            usage.input_tokens * self._pricing.input_usd_per_million
            + usage.output_tokens * self._pricing.output_usd_per_million
        ) / 1_000_000
        return self._store.add_llm_usage(run_id, usage.input_tokens, usage.output_tokens, cost)

    def reserve_tool_call(self, run_id: str) -> BudgetDecision:
        return self._audited(
            run_id, "tool", self._store.reserve_tool_call(run_id, self._settings.budgets)
        )

    def run_usage(self, run_id: str) -> RunUsage:
        return self._store.run_usage(run_id)

    def _audited(self, run_id: str, kind: str, decision: BudgetDecision) -> BudgetDecision:
        if not decision.allowed:
            self.record(
                "system",
                "budget.exhausted",
                target=run_id,
                detail={"kind": kind, "reason": decision.reason},
            )
        return decision

    # circuit breakers

    def breaker_allows(self, resource: str) -> bool:
        before, after = self._store.breaker_allow(
            resource, self._clock(), self._settings.breakers.cooldown_seconds
        )
        self._note_breaker(resource, before, after)
        return after.state != "open"

    def breaker_success(self, resource: str) -> BreakerState:
        return self._record_breaker(resource, success=True)

    def breaker_failure(self, resource: str) -> BreakerState:
        return self._record_breaker(resource, success=False)

    def breaker(self, resource: str) -> BreakerState | None:
        return self._store.get_breaker(resource)

    def reset_breaker(self, actor: str, resource: str) -> BreakerState:
        target = f"breaker:{resource}"
        self.require(actor, MANAGE_BREAKERS, target=target)
        before, after = self._store.breaker_reset(resource, self._clock())
        self.record(actor, "breaker.reset", target=target, detail={"from": before})
        return after

    def _record_breaker(self, resource: str, *, success: bool) -> BreakerState:
        before, after = self._store.breaker_record(
            resource,
            self._clock(),
            success=success,
            threshold=self._settings.breakers.failure_threshold,
        )
        self._note_breaker(resource, before, after)
        return after

    def _note_breaker(self, resource: str, before: str, after: BreakerState) -> None:
        if before != after.state:
            self.record(
                "system",
                f"breaker.{after.state}",
                target=f"breaker:{resource}",
                detail={"from": before, "failures": after.failures},
            )
