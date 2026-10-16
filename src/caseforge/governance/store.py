"""Governance database: kept apart from case records and only reachable via the ControlPlane.

The audit log is append-only: triggers abort any UPDATE or DELETE. Triggers stop the
application from changing history; they do not protect against a privileged process
that can alter the database schema itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from caseforge.common.hashing import canonical_json_bytes
from caseforge.common.sqlite import SqliteDatabase
from caseforge.governance.models import AuditEntry, SwitchState

SCHEMA_VERSION: Final = "governance.v2"
_STATEMENTS: Final = (
    """CREATE TABLE IF NOT EXISTS audit_log (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        target TEXT NOT NULL,
        outcome TEXT NOT NULL,
        detail TEXT NOT NULL
    )""",
    """CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END""",
)
_V2_STATEMENTS: Final = (
    """CREATE TABLE IF NOT EXISTS switches (
        name TEXT PRIMARY KEY,
        engaged INTEGER NOT NULL,
        actor TEXT NOT NULL,
        reason TEXT NOT NULL,
        changed_at TEXT NOT NULL
    )""",
)


class GovernanceError(RuntimeError):
    """Raised for incompatible or unusable governance storage."""


class GovernanceStore:
    def __init__(self, path: str | Path) -> None:
        self._db = SqliteDatabase(
            path,
            label="governance",
            schema_version=SCHEMA_VERSION,
            base_statements=(*_STATEMENTS, *_V2_STATEMENTS),
            migrations={"governance.v1": ("governance.v2", _V2_STATEMENTS)},
            error=GovernanceError,
        )

    def close(self) -> None:
        self._db.close()

    def append_audit(self, entry: AuditEntry) -> AuditEntry:
        data = entry.model_dump(mode="json", exclude={"seq"})
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO audit_log (at, actor, action, target, outcome, detail) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    data["at"],
                    entry.actor,
                    entry.action,
                    entry.target,
                    entry.outcome,
                    canonical_json_bytes(entry.detail).decode("utf-8"),
                ),
            )
        return entry.model_copy(update={"seq": cursor.lastrowid})

    def audit_entries(
        self, *, action: str | None = None, target: str | None = None
    ) -> tuple[AuditEntry, ...]:
        clauses, params = [], []
        if action is not None:
            clauses.append("action = ?")
            params.append(action)
        if target is not None:
            clauses.append("target = ?")
            params.append(target)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._db.reading() as conn:
            rows = conn.execute(
                "SELECT seq, at, actor, action, target, outcome, detail FROM audit_log"
                f"{where} ORDER BY seq",
                params,
            ).fetchall()
        return tuple(
            AuditEntry(
                seq=seq,
                at=at,
                actor=actor,
                action=act,
                target=tgt,
                outcome=outcome,
                detail=json.loads(detail),
            )
            for seq, at, actor, act, tgt, outcome, detail in rows
        )

    def set_switch(self, state: SwitchState) -> None:
        data = state.model_dump(mode="json")
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO switches (name, engaged, actor, reason, changed_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                "engaged = excluded.engaged, actor = excluded.actor, "
                "reason = excluded.reason, changed_at = excluded.changed_at",
                (state.name, int(state.engaged), state.actor, state.reason, data["changed_at"]),
            )

    def get_switch(self, name: str) -> SwitchState | None:
        with self._db.reading() as conn:
            row = conn.execute(
                "SELECT name, engaged, actor, reason, changed_at FROM switches WHERE name = ?",
                (name,),
            ).fetchone()
        if row is None:
            return None
        return SwitchState(
            name=row[0], engaged=bool(row[1]), actor=row[2], reason=row[3], changed_at=row[4]
        )
