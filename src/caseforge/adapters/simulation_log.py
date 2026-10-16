"""The simulated outside world's own durable storage: registered cases and applied actions.

Kept in a database separate from CaseForge's records, as a real external system would
keep its own. Worlds are rebuilt deterministically by re-applying logged actions in order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from caseforge.common.sqlite import SqliteDatabase

SCHEMA_VERSION: Final = "simulation.v1"
_STATEMENTS: Final = (
    """CREATE TABLE IF NOT EXISTS cases (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        case_id TEXT NOT NULL,
        family_id TEXT NOT NULL,
        seed INTEGER NOT NULL,
        start_at TEXT NOT NULL,
        UNIQUE (tenant_id, case_id)
    )""",
    """CREATE TABLE IF NOT EXISTS actions (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        case_id TEXT NOT NULL,
        action_id TEXT NOT NULL,
        action_type TEXT NOT NULL,
        at TEXT NOT NULL,
        UNIQUE (tenant_id, case_id, action_id)
    )""",
)


class SimulationLogError(ValueError):
    """Raised for incompatible simulation storage or conflicting case registrations."""


@dataclass(frozen=True)
class LoggedCase:
    tenant_id: str
    case_id: str
    family_id: str
    seed: int
    start_at: datetime


@dataclass(frozen=True)
class LoggedAction:
    action_id: str
    action_type: str
    at: datetime


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


class SqliteSimulationLog:
    def __init__(self, path: str | Path) -> None:
        self._db = SqliteDatabase(
            path,
            label="simulation",
            schema_version=SCHEMA_VERSION,
            base_statements=_STATEMENTS,
            migrations={},
            error=SimulationLogError,
        )

    def close(self) -> None:
        self._db.close()

    def register_case(self, case: LoggedCase) -> None:
        """Record a case once; re-registering with different parameters is refused."""
        params = (case.family_id, case.seed, _iso(case.start_at))
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT family_id, seed, start_at FROM cases WHERE tenant_id = ? AND case_id = ?",
                (case.tenant_id, case.case_id),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO cases (tenant_id, case_id, family_id, seed, start_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (case.tenant_id, case.case_id, *params),
                )
            elif tuple(row) != params:
                raise SimulationLogError(
                    f"case {case.case_id!r} already registered with different parameters"
                )

    def append_action(
        self, tenant_id: str, case_id: str, action_id: str, action_type: str, at: datetime
    ) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO actions "
                "(tenant_id, case_id, action_id, action_type, at) VALUES (?, ?, ?, ?, ?)",
                (tenant_id, case_id, action_id, action_type, _iso(at)),
            )

    def cases(self) -> tuple[LoggedCase, ...]:
        with self._db.reading() as conn:
            rows = conn.execute(
                "SELECT tenant_id, case_id, family_id, seed, start_at FROM cases ORDER BY seq"
            ).fetchall()
        return tuple(
            LoggedCase(t, c, f, int(s), datetime.fromisoformat(at)) for t, c, f, s, at in rows
        )

    def actions(self, tenant_id: str, case_id: str) -> tuple[LoggedAction, ...]:
        with self._db.reading() as conn:
            rows = conn.execute(
                "SELECT action_id, action_type, at FROM actions "
                "WHERE tenant_id = ? AND case_id = ? ORDER BY seq",
                (tenant_id, case_id),
            ).fetchall()
        return tuple(LoggedAction(a, t, datetime.fromisoformat(at)) for a, t, at in rows)
