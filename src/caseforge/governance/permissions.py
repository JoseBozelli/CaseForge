"""Catalog of governed operations.

Fixed in code on purpose: configuration may only grant permissions listed here, so it
cannot invent new powers. Later governance steps add entries.
"""

from __future__ import annotations

from typing import Final

APPROVE_ACTION: Final = "approve_action"
EMERGENCY_STOP: Final = "emergency_stop"
MANAGE_BREAKERS: Final = "manage_breakers"
RECONCILE_ACTION: Final = "reconcile_action"

PERMISSIONS: Final = frozenset({APPROVE_ACTION, EMERGENCY_STOP, MANAGE_BREAKERS, RECONCILE_ACTION})
