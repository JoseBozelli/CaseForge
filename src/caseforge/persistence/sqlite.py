"""SQLite RecordStore: durable, transactional, single-file storage.

Writes run inside BEGIN IMMEDIATE transactions; the database uses WAL journaling.
Records are stored as canonical JSON plus indexed key columns. The schema version
is checked on open; unsupported versions are refused rather than migrated.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Final

from caseforge.events.envelope import EventEnvelope
from caseforge.events.mapping import Rejection
from caseforge.persistence.codec import (
    decode_event,
    decode_rejection,
    encode_event,
    encode_rejection,
)
from caseforge.persistence.ports import IntakeResult, RecordConflictError, RecordStoreError
from caseforge.provenance.manifest import RunManifest

SCHEMA_VERSION: Final = "records.v1"

_SCHEMA_STATEMENTS: Final = (
    "CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
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


def _time_key(moment: datetime) -> str:
    """Fixed-width UTC key whose text order equals chronological order."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class SqliteRecordStore:
    """Durable RecordStore backed by one SQLite file."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, isolation_level=None, check_same_thread=False)
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._initialize()
        except BaseException:
            self._conn.close()
            raise

    def __enter__(self) -> SqliteRecordStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _initialize(self) -> None:
        with self._transaction() as conn:
            for statement in _SCHEMA_STATEMENTS:
                conn.execute(statement)
            row = conn.execute("SELECT value FROM schema_info WHERE key = 'schema'").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO schema_info (key, value) VALUES ('schema', ?)", (SCHEMA_VERSION,)
                )
            elif row[0] != SCHEMA_VERSION:
                raise RecordStoreError(
                    f"unsupported records schema {row[0]!r}; expected {SCHEMA_VERSION!r}"
                )

    def save_manifest(self, manifest: RunManifest) -> None:
        payload, digest = manifest.to_json_bytes().decode("utf-8"), manifest.sha256()
        with self._transaction() as conn:
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
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM run_manifests WHERE run_id = ?", (run_id,)
            ).fetchone()
        return None if row is None else RunManifest.model_validate_json(row[0])

    def append_events(self, events: Iterable[EventEnvelope]) -> IntakeResult:
        inserted: list[str] = []
        duplicates: list[str] = []
        conflicts: list[str] = []
        with self._transaction() as conn:
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
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM events WHERE tenant_id = ? AND case_id = ? "
                "ORDER BY recorded_key, event_id",
                (tenant_id, case_id),
            ).fetchall()
        return tuple(decode_event(row[0]) for row in rows)

    def save_rejections(self, rejections: Iterable[Rejection]) -> int:
        count = 0
        with self._transaction() as conn:
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
        with self._lock:
            rows = self._conn.execute(query + " ORDER BY seq", params).fetchall()
        return tuple(decode_rejection(row[0]) for row in rows)
