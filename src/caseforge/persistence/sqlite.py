"""SQLite RecordStore: durable, transactional, single-file storage.

Writes run inside BEGIN IMMEDIATE transactions; the database uses WAL journaling.
Records are stored as canonical JSON plus indexed key columns. Older schema versions
are upgraded by a forward-only migration chain; unknown versions are refused.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, Final, TypeVar

from pydantic import BaseModel

from caseforge.common.sqlite import SqliteDatabase
from caseforge.events.envelope import EventEnvelope
from caseforge.events.mapping import Rejection
from caseforge.persistence.codec import (
    decode_event,
    decode_rejection,
    encode_event,
    encode_model,
    encode_rejection,
)
from caseforge.persistence.errors import (
    LedgerTransitionError,
    RecordConflictError,
    RecordStoreError,
)
from caseforge.persistence.ports import IntakeResult
from caseforge.persistence.records import (
    ActionLedgerEntry,
    ApprovalRecord,
    DecisionRecord,
    DecisionSave,
    EpisodeRecord,
    LedgerStatus,
    transition,
)
from caseforge.provenance.manifest import RunManifest
from caseforge.reasoning.models import LlmCallRecord
from caseforge.tools.models import ToolInvocationRecord

SCHEMA_VERSION: Final = "records.v4"
R = TypeVar("R", bound=BaseModel)

_V1_STATEMENTS: Final = (
    """CREATE TABLE IF NOT EXISTS run_manifests (
        run_id TEXT PRIMARY KEY,
        sha256 TEXT NOT NULL,
        payload TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS events (
        tenant_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        case_id TEXT,
        recorded_key TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (tenant_id, event_id)
    )""",
    """CREATE INDEX IF NOT EXISTS events_by_case
        ON events (tenant_id, case_id, recorded_key, event_id)""",
    """CREATE TABLE IF NOT EXISTS rejections (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        source_system TEXT NOT NULL,
        source_event_id TEXT NOT NULL,
        mapping_id TEXT NOT NULL,
        mapping_version INTEGER NOT NULL,
        raw_sha256 TEXT NOT NULL,
        code TEXT NOT NULL,
        payload TEXT NOT NULL,
        UNIQUE (source_system, source_event_id, mapping_id, mapping_version, raw_sha256)
    )""",
)
_V2_STATEMENTS: Final = (
    """CREATE TABLE IF NOT EXISTS llm_calls (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        call_id TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        payload TEXT NOT NULL,
        UNIQUE (call_id, sha256)
    )""",
    "CREATE INDEX IF NOT EXISTS llm_calls_by_run ON llm_calls (run_id, seq)",
    """CREATE TABLE IF NOT EXISTS tool_invocations (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        invocation_id TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        payload TEXT NOT NULL,
        UNIQUE (invocation_id, sha256)
    )""",
    "CREATE INDEX IF NOT EXISTS tool_invocations_by_run ON tool_invocations (run_id, seq)",
    """CREATE TABLE IF NOT EXISTS decisions (
        run_id TEXT PRIMARY KEY,
        material_sha256 TEXT NOT NULL,
        payload TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS action_ledger (
        idempotency_key TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        status TEXT NOT NULL,
        payload TEXT NOT NULL
    )""",
)
_V3_STATEMENTS: Final = (
    """CREATE TABLE IF NOT EXISTS approvals (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        payload TEXT NOT NULL,
        UNIQUE (run_id, sha256)
    )""",
)
_V4_STATEMENTS: Final = (
    """CREATE TABLE IF NOT EXISTS episodes (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL UNIQUE,
        tenant_id TEXT NOT NULL,
        case_id TEXT NOT NULL,
        payload TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS episodes_by_tenant ON episodes (tenant_id, seq)",
)
_MIGRATIONS: Final = {
    "records.v1": ("records.v2", _V2_STATEMENTS),
    "records.v2": ("records.v3", _V3_STATEMENTS),
    "records.v3": ("records.v4", _V4_STATEMENTS),
}


def _time_key(moment: datetime) -> str:
    """Fixed-width UTC key whose text order equals chronological order."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class SqliteRecordStore:
    """Durable RecordStore backed by one SQLite file."""

    def __init__(self, path: str | Path) -> None:
        self._db = SqliteDatabase(
            path,
            label="records",
            schema_version=SCHEMA_VERSION,
            base_statements=(*_V1_STATEMENTS, *_V2_STATEMENTS, *_V3_STATEMENTS, *_V4_STATEMENTS),
            migrations=_MIGRATIONS,
            error=RecordStoreError,
        )

    def __enter__(self) -> SqliteRecordStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    # manifests, events and rejections

    def save_manifest(self, manifest: RunManifest) -> None:
        payload, digest = manifest.to_json_bytes().decode("utf-8"), manifest.sha256()
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT sha256 FROM run_manifests WHERE run_id = ?", (manifest.run_id,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO run_manifests (run_id, sha256, payload) VALUES (?, ?, ?)",
                    (manifest.run_id, digest, payload),
                )
            elif row[0] != digest:
                raise RecordConflictError(
                    f"run {manifest.run_id!r} already recorded with different content"
                )

    def get_manifest(self, run_id: str) -> RunManifest | None:
        with self._db.reading() as conn:
            row = conn.execute(
                "SELECT payload FROM run_manifests WHERE run_id = ?", (run_id,)
            ).fetchone()
        return None if row is None else RunManifest.model_validate_json(row[0])

    def append_events(self, events: Iterable[EventEnvelope]) -> IntakeResult:
        inserted: list[str] = []
        duplicates: list[str] = []
        conflicts: list[str] = []
        with self._db.transaction() as conn:
            for event in events:
                payload, digest = encode_event(event)
                row = conn.execute(
                    "SELECT sha256 FROM events WHERE tenant_id = ? AND event_id = ?",
                    (event.tenant_id, event.event_id),
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO events "
                        "(tenant_id, event_id, case_id, recorded_key, sha256, payload) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            event.tenant_id,
                            event.event_id,
                            event.case_id,
                            _time_key(event.recorded_at),
                            digest,
                            payload,
                        ),
                    )
                    inserted.append(event.event_id)
                elif row[0] == digest:
                    duplicates.append(event.event_id)
                else:
                    conflicts.append(event.event_id)
        return IntakeResult(tuple(inserted), tuple(duplicates), tuple(conflicts))

    def events_for_case(self, tenant_id: str, case_id: str) -> tuple[EventEnvelope, ...]:
        with self._db.reading() as conn:
            rows = conn.execute(
                "SELECT payload FROM events WHERE tenant_id = ? AND case_id = ? "
                "ORDER BY recorded_key, event_id",
                (tenant_id, case_id),
            ).fetchall()
        return tuple(decode_event(row[0]) for row in rows)

    def save_rejections(self, rejections: Iterable[Rejection]) -> int:
        count = 0
        with self._db.transaction() as conn:
            for rejection in rejections:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO rejections "
                    "(source_system, source_event_id, mapping_id, mapping_version, "
                    "raw_sha256, code, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        rejection.source_system,
                        rejection.source_event_id,
                        rejection.mapping_id,
                        rejection.mapping_version,
                        rejection.raw_sha256,
                        str(rejection.code),
                        encode_rejection(rejection),
                    ),
                )
                count += cursor.rowcount
        return count

    def list_rejections(self, source_system: str | None = None) -> tuple[Rejection, ...]:
        query = "SELECT payload FROM rejections"
        params: tuple[str, ...] = ()
        if source_system is not None:
            query += " WHERE source_system = ?"
            params = (source_system,)
        with self._db.reading() as conn:
            rows = conn.execute(query + " ORDER BY seq", params).fetchall()
        return tuple(decode_rejection(row[0]) for row in rows)

    # model and tool call records (append-only)

    def _append(
        self, table: str, id_column: str, records: Iterable[R], identity: Callable[[R], str]
    ) -> int:
        count = 0
        with self._db.transaction() as conn:
            for record in records:
                payload, digest = encode_model(record)
                cursor = conn.execute(
                    f"INSERT OR IGNORE INTO {table} (run_id, {id_column}, sha256, payload) "
                    "VALUES (?, ?, ?, ?)",
                    (record.run_id, identity(record), digest, payload),
                )
                count += cursor.rowcount
        return count

    def _list(self, table: str, run_id: str, model: type[R]) -> tuple[R, ...]:
        with self._db.reading() as conn:
            rows = conn.execute(
                f"SELECT payload FROM {table} WHERE run_id = ? ORDER BY seq", (run_id,)
            ).fetchall()
        return tuple(model.model_validate_json(row[0]) for row in rows)

    def save_llm_calls(self, records: Iterable[LlmCallRecord]) -> int:
        return self._append("llm_calls", "call_id", records, lambda r: r.call_id)

    def llm_calls_for_run(self, run_id: str) -> tuple[LlmCallRecord, ...]:
        return self._list("llm_calls", run_id, LlmCallRecord)

    def save_tool_invocations(self, records: Iterable[ToolInvocationRecord]) -> int:
        return self._append("tool_invocations", "invocation_id", records, lambda r: r.invocation_id)

    def tool_invocations_for_run(self, run_id: str) -> tuple[ToolInvocationRecord, ...]:
        return self._list("tool_invocations", run_id, ToolInvocationRecord)

    # decisions (first committed decision wins)

    def save_decision(self, record: DecisionRecord) -> DecisionSave:
        payload, _ = encode_model(record)
        material = record.material_sha256()
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT material_sha256, payload FROM decisions WHERE run_id = ?",
                (record.run_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO decisions (run_id, material_sha256, payload) VALUES (?, ?, ?)",
                    (record.run_id, material, payload),
                )
                return DecisionSave(record, "inserted")
        stored = DecisionRecord.model_validate_json(row[1])
        return DecisionSave(stored, "duplicate" if row[0] == material else "conflict")

    def get_decision(self, run_id: str) -> DecisionRecord | None:
        with self._db.reading() as conn:
            row = conn.execute(
                "SELECT payload FROM decisions WHERE run_id = ?", (run_id,)
            ).fetchone()
        return None if row is None else DecisionRecord.model_validate_json(row[0])

    # action ledger

    def begin_action(self, entry: ActionLedgerEntry) -> ActionLedgerEntry:
        if entry.status != LedgerStatus.INTENT:
            raise LedgerTransitionError("a ledger entry must begin in the intent status")
        payload, _ = encode_model(entry)
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT payload FROM action_ledger WHERE idempotency_key = ?",
                (entry.idempotency_key,),
            ).fetchone()
            if row is not None:
                return ActionLedgerEntry.model_validate_json(row[0])
            conn.execute(
                "INSERT INTO action_ledger (idempotency_key, run_id, status, payload) "
                "VALUES (?, ?, ?, ?)",
                (entry.idempotency_key, entry.run_id, str(entry.status), payload),
            )
        return entry

    def transition_action(
        self,
        idempotency_key: str,
        status: LedgerStatus,
        *,
        at: datetime,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> ActionLedgerEntry:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT payload FROM action_ledger WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is None:
                raise RecordStoreError(f"unknown action {idempotency_key!r}")
            current = ActionLedgerEntry.model_validate_json(row[0])
            updated = transition(current, status, at=at, result=result, error=error)
            payload, _ = encode_model(updated)
            conn.execute(
                "UPDATE action_ledger SET status = ?, payload = ? WHERE idempotency_key = ?",
                (str(updated.status), payload, idempotency_key),
            )
        return updated

    def get_action(self, idempotency_key: str) -> ActionLedgerEntry | None:
        with self._db.reading() as conn:
            row = conn.execute(
                "SELECT payload FROM action_ledger WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return None if row is None else ActionLedgerEntry.model_validate_json(row[0])

    # approvals (append-only)

    def save_approval(self, record: ApprovalRecord) -> bool:
        payload, digest = encode_model(record)
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO approvals (run_id, sha256, payload) VALUES (?, ?, ?)",
                (record.run_id, digest, payload),
            )
        return cursor.rowcount == 1

    def approvals_for_run(self, run_id: str) -> tuple[ApprovalRecord, ...]:
        return self._list("approvals", run_id, ApprovalRecord)

    # episodes (one per run; a re-run replaces it)

    def save_episode(self, record: EpisodeRecord) -> None:
        payload, _ = encode_model(record)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO episodes (run_id, tenant_id, case_id, payload) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET "
                "tenant_id = excluded.tenant_id, case_id = excluded.case_id, "
                "payload = excluded.payload",
                (record.run_id, record.tenant_id, record.case_id, payload),
            )

    def episodes_for_tenant(self, tenant_id: str) -> tuple[EpisodeRecord, ...]:
        with self._db.reading() as conn:
            rows = conn.execute(
                "SELECT payload FROM episodes WHERE tenant_id = ? ORDER BY seq", (tenant_id,)
            ).fetchall()
        return tuple(EpisodeRecord.model_validate_json(row[0]) for row in rows)
