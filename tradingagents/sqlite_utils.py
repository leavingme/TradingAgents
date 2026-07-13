"""Consistent, bounded-concurrency settings for project SQLite stores."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


class RetryingConnection(sqlite3.Connection):
    """Retry only transient lock/busy operations; surface all other failures."""

    def execute(self, sql: str, parameters: Any = (), /):
        attempts = 5
        for attempt in range(attempts):
            try:
                return super().execute(sql, parameters)
            except sqlite3.OperationalError as exc:
                transient = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if not transient or attempt == attempts - 1:
                    raise
                time.sleep(0.025 * (2 ** attempt))
        raise AssertionError("unreachable")

    def commit(self) -> None:
        attempts = 5
        for attempt in range(attempts):
            try:
                return super().commit()
            except sqlite3.OperationalError as exc:
                transient = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if not transient or attempt == attempts - 1:
                    raise
                time.sleep(0.025 * (2 ** attempt))


def connect_sqlite(
    path: str | Path, *, check_same_thread: bool = True
) -> RetryingConnection:
    conn = sqlite3.connect(
        str(path), timeout=30, check_same_thread=check_same_thread,
        factory=RetryingConnection,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def configure_wal(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
