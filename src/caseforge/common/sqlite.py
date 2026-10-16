"""Shared SQLite plumbing: WAL connection, immediate write transactions, versioned schemas.

A fresh database receives base_statements and schema_version. An existing database is
upgraded through migrations (from-version -> (to-version, statements)) until it reaches
schema_version; an unknown version raises the caller's error type.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path


class SqliteDatabase:
    def __init__(
        self,
        path: str | Path,
        *,
        label: str,
        schema_version: str,
        base_statements: Sequence[str],
        migrations: Mapping[str, tuple[str, Sequence[str]]],
        error: type[Exception],
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._initialize(label, schema_version, base_statements, migrations, error)
        except BaseException:
            self._conn.close()
            raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialized write transaction; rolled back on any exception."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    @contextmanager
    def reading(self) -> Iterator[sqlite3.Connection]:
        """Serialized access for reads."""
        with self._lock:
            yield self._conn

    def close(self) -> None:
        self._conn.close()

    def _initialize(
        self,
        label: str,
        schema_version: str,
        base_statements: Sequence[str],
        migrations: Mapping[str, tuple[str, Sequence[str]]],
        error: type[Exception],
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = conn.execute("SELECT value FROM schema_info WHERE key = 'schema'").fetchone()
            if row is None:
                for statement in base_statements:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_info (key, value) VALUES ('schema', ?)", (schema_version,)
                )
                return
            version = row[0]
            while version != schema_version:
                step = migrations.get(version)
                if step is None:
                    raise error(
                        f"unsupported {label} schema {version!r}; expected {schema_version!r}"
                    )
                version, statements = step
                for statement in statements:
                    conn.execute(statement)
            conn.execute("UPDATE schema_info SET value = ? WHERE key = 'schema'", (version,))
