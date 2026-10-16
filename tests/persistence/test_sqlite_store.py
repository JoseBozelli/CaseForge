"""SQLite-specific behavior: durability, schema versioning and journaling."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from caseforge.persistence.ports import RecordStoreError
from caseforge.persistence.records import ActionLedgerEntry, LedgerStatus
from caseforge.persistence.sqlite import SqliteRecordStore

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def test_data_survives_reopen(tmp_path: Path, make_event) -> None:
    path = tmp_path / "records.db"
    with SqliteRecordStore(path) as store:
        store.append_events([make_event()])
    with SqliteRecordStore(path) as store:
        assert store.events_for_case("tenant-a", "case-0001") == (make_event(),)


def test_schema_version_mismatch_rejected(tmp_path: Path) -> None:
    path = tmp_path / "records.db"
    SqliteRecordStore(path).close()
    conn = sqlite3.connect(path)
    conn.execute("UPDATE schema_info SET value = 'records.v0' WHERE key = 'schema'")
    conn.commit()
    conn.close()
    with pytest.raises(RecordStoreError, match="schema"):
        SqliteRecordStore(path)


def test_wal_journaling_enabled(tmp_path: Path) -> None:
    path = tmp_path / "records.db"
    SqliteRecordStore(path).close()
    conn = sqlite3.connect(path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_parent_directories_created(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "records.db"
    with SqliteRecordStore(path):
        pass
    assert path.exists()


def test_v1_database_is_migrated_to_v2(tmp_path: Path, make_event) -> None:
    path = tmp_path / "records.db"
    with SqliteRecordStore(path) as store:
        store.append_events([make_event()])
    conn = sqlite3.connect(path)
    for table in ("llm_calls", "tool_invocations", "decisions", "action_ledger", "approvals"):
        conn.execute(f"DROP TABLE {table}")
    conn.execute("UPDATE schema_info SET value = 'records.v1' WHERE key = 'schema'")
    conn.commit()
    conn.close()

    with SqliteRecordStore(path) as store:
        assert store.events_for_case("tenant-a", "case-0001") == (make_event(),)
        assert store.get_action("missing") is None

    conn = sqlite3.connect(path)
    version = conn.execute("SELECT value FROM schema_info WHERE key = 'schema'").fetchone()[0]
    conn.close()
    assert version == "records.v3"


def test_ledger_state_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "records.db"
    entry = ActionLedgerEntry(
        idempotency_key="run-0001:send_reminder",
        run_id="run-0001",
        case_id="case-0001",
        tenant_id="tenant-a",
        action_type="send_reminder",
        created_at=T0,
        updated_at=T0,
    )
    with SqliteRecordStore(path) as store:
        store.begin_action(entry)
        store.transition_action(entry.idempotency_key, LedgerStatus.DISPATCHED, at=T0)
    with SqliteRecordStore(path) as store:
        stored = store.get_action(entry.idempotency_key)
    assert (stored.status, stored.attempts) == (LedgerStatus.DISPATCHED, 1)
