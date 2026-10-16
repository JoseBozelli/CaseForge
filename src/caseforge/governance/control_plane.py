"""ControlPlane: decides and records governed operations.

Agents never receive this object. Operator identities are supplied by the caller and
are not authenticated here (simulated identity); roles and permissions come from
trusted configuration.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from caseforge.governance.models import AuditEntry
from caseforge.governance.permissions import PERMISSIONS
from caseforge.governance.store import GovernanceStore
from caseforge.settings.models import GovernanceSettings


class PermissionDenied(Exception):
    """Raised when an operator lacks the permission for a governed operation."""


class ControlPlane:
    def __init__(
        self,
        store: GovernanceStore,
        settings: GovernanceSettings,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._settings = settings
        self._clock = clock

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
