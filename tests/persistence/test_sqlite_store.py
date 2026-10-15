"""SQLite-specific behavior: durability, schema versioning and journaling."""

import sqlite3
from pathlib import Path

import pytest

from caseforge.persistence.ports import RecordStoreError
from caseforge.persistence.sqlite import SqliteRecordStore


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
