"""Governance database: kept apart from case records and only reachable via the ControlPlane.

The audit log is append-only: triggers abort any UPDATE or DELETE. Triggers stop the
application from changing history; they do not protect against a privileged process
that can alter the database schema itself.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from caseforge.common.hashing import canonical_json_bytes
from caseforge.common.sqlite import SqliteDatabase
from caseforge.governance.models import (
    AuditEntry,
    BreakerState,
    BudgetDecision,
    RunUsage,
    SwitchState,
)
from caseforge.settings.models import BudgetSettings

SCHEMA_VERSION: Final = "governance.v4"
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
_V3_STATEMENTS: Final = (
    """CREATE TABLE IF NOT EXISTS run_usage (
        run_id TEXT PRIMARY KEY,
        llm_calls INTEGER NOT NULL DEFAULT 0,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        cost_usd REAL NOT NULL DEFAULT 0,
        tool_calls INTEGER NOT NULL DEFAULT 0
    )""",
)
_V4_STATEMENTS: Final = (
    """CREATE TABLE IF NOT EXISTS breakers (
        resource TEXT PRIMARY KEY,
        state TEXT NOT NULL,
        failures INTEGER NOT NULL,
        opened_at TEXT,
        updated_at TEXT NOT NULL
    )""",
)


class GovernanceError(RuntimeError):
    """Raised for incompatible or unusable governance storage."""


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


class GovernanceStore:
    def __init__(self, path: str | Path) -> None:
        self._db = SqliteDatabase(
            path,
            label="governance",
            schema_version=SCHEMA_VERSION,
            base_statements=(*_STATEMENTS, *_V2_STATEMENTS, *_V3_STATEMENTS, *_V4_STATEMENTS),
            migrations={
                "governance.v1": ("governance.v2", _V2_STATEMENTS),
                "governance.v2": ("governance.v3", _V3_STATEMENTS),
                "governance.v3": ("governance.v4", _V4_STATEMENTS),
            },
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

    # per-run budgets: check and count in one transaction

    def run_usage(self, run_id: str) -> RunUsage:
        with self._db.transaction() as conn:
            return self._usage(conn, run_id)

    def reserve_llm_call(self, run_id: str, limits: BudgetSettings) -> BudgetDecision:
        with self._db.transaction() as conn:
            usage = self._usage(conn, run_id)
            reason = None
            if usage.llm_calls >= limits.max_llm_calls:
                reason = f"model call limit reached ({limits.max_llm_calls})"
            elif usage.total_tokens >= limits.max_total_tokens:
                reason = f"token limit reached ({limits.max_total_tokens})"
            elif usage.cost_usd >= limits.max_cost_usd:
                reason = f"cost limit reached ({limits.max_cost_usd} USD)"
            if reason is not None:
                return BudgetDecision(allowed=False, reason=reason, usage=usage)
            conn.execute(
                "UPDATE run_usage SET llm_calls = llm_calls + 1 WHERE run_id = ?", (run_id,)
            )
            return BudgetDecision(allowed=True, usage=self._usage(conn, run_id))

    def add_llm_usage(
        self, run_id: str, input_tokens: int, output_tokens: int, cost_usd: float
    ) -> RunUsage:
        with self._db.transaction() as conn:
            self._usage(conn, run_id)
            conn.execute(
                "UPDATE run_usage SET input_tokens = input_tokens + ?, "
                "output_tokens = output_tokens + ?, cost_usd = cost_usd + ? WHERE run_id = ?",
                (input_tokens, output_tokens, cost_usd, run_id),
            )
            return self._usage(conn, run_id)

    def reserve_tool_call(self, run_id: str, limits: BudgetSettings) -> BudgetDecision:
        with self._db.transaction() as conn:
            usage = self._usage(conn, run_id)
            if usage.tool_calls >= limits.max_tool_calls:
                return BudgetDecision(
                    allowed=False,
                    reason=f"tool call limit reached ({limits.max_tool_calls})",
                    usage=usage,
                )
            conn.execute(
                "UPDATE run_usage SET tool_calls = tool_calls + 1 WHERE run_id = ?", (run_id,)
            )
            return BudgetDecision(allowed=True, usage=self._usage(conn, run_id))

    @staticmethod
    def _usage(conn, run_id: str) -> RunUsage:
        conn.execute("INSERT OR IGNORE INTO run_usage (run_id) VALUES (?)", (run_id,))
        row = conn.execute(
            "SELECT llm_calls, input_tokens, output_tokens, cost_usd, tool_calls "
            "FROM run_usage WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return RunUsage(
            run_id=run_id,
            llm_calls=row[0],
            input_tokens=row[1],
            output_tokens=row[2],
            cost_usd=row[3],
            tool_calls=row[4],
        )

    # circuit breakers

    def get_breaker(self, resource: str) -> BreakerState | None:
        with self._db.reading() as conn:
            row = conn.execute(
                "SELECT resource, state, failures, opened_at, updated_at FROM breakers "
                "WHERE resource = ?",
                (resource,),
            ).fetchone()
        return None if row is None else self._row_to_breaker(row)

    def breaker_allow(
        self, resource: str, now: datetime, cooldown_seconds: float
    ) -> tuple[str, BreakerState]:
        """Move open -> half_open once the cool-down has passed. Returns (before, after)."""
        with self._db.transaction() as conn:
            current = self._breaker(conn, resource, now)
            cooled = (
                current.state == "open"
                and current.opened_at is not None
                and (now - current.opened_at).total_seconds() >= cooldown_seconds
            )
            if cooled:
                conn.execute(
                    "UPDATE breakers SET state = 'half_open', updated_at = ? WHERE resource = ?",
                    (_iso(now), resource),
                )
                return current.state, self._breaker(conn, resource, now)
            return current.state, current

    def breaker_record(
        self, resource: str, now: datetime, *, success: bool, threshold: int
    ) -> tuple[str, BreakerState]:
        with self._db.transaction() as conn:
            current = self._breaker(conn, resource, now)
            if success:
                conn.execute(
                    "UPDATE breakers SET state = 'closed', failures = 0, opened_at = NULL, "
                    "updated_at = ? WHERE resource = ?",
                    (_iso(now), resource),
                )
            else:
                failures = current.failures + 1
                if current.state == "half_open" or failures >= threshold:
                    conn.execute(
                        "UPDATE breakers SET state = 'open', failures = ?, opened_at = ?, "
                        "updated_at = ? WHERE resource = ?",
                        (failures, _iso(now), _iso(now), resource),
                    )
                else:
                    conn.execute(
                        "UPDATE breakers SET failures = ?, updated_at = ? WHERE resource = ?",
                        (failures, _iso(now), resource),
                    )
            return current.state, self._breaker(conn, resource, now)

    def breaker_reset(self, resource: str, now: datetime) -> tuple[str, BreakerState]:
        return self.breaker_record(resource, now, success=True, threshold=1)

    @classmethod
    def _breaker(cls, conn, resource: str, now: datetime) -> BreakerState:
        conn.execute(
            "INSERT OR IGNORE INTO breakers (resource, state, failures, opened_at, updated_at) "
            "VALUES (?, 'closed', 0, NULL, ?)",
            (resource, _iso(now)),
        )
        row = conn.execute(
            "SELECT resource, state, failures, opened_at, updated_at FROM breakers "
            "WHERE resource = ?",
            (resource,),
        ).fetchone()
        return cls._row_to_breaker(row)

    @staticmethod
    def _row_to_breaker(row) -> BreakerState:
        return BreakerState(
            resource=row[0], state=row[1], failures=row[2], opened_at=row[3], updated_at=row[4]
        )
