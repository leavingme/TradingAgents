"""Persist the latest real request result for each vendor capability."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tradingagents.sqlite_utils import configure_wal, connect_sqlite


def _default_db_path() -> Path:
    configured = os.environ.get("TRADINGAGENTS_DB")
    if configured:
        return Path(configured)
    return Path.home() / ".tradingagents" / "runs.db"


class VendorVerificationStore:
    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            configure_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vendor_verifications (
                    vendor      TEXT NOT NULL,
                    category    TEXT NOT NULL,
                    method      TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    source      TEXT NOT NULL,
                    detail      TEXT,
                    latency_ms  INTEGER,
                    verified_at TEXT NOT NULL,
                    PRIMARY KEY (vendor, category)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path)

    def record(
        self,
        *,
        vendor: str,
        category: str,
        method: str,
        status: str,
        source: str,
        detail: str | None = None,
        latency_ms: int | None = None,
    ) -> dict[str, Any]:
        verified_at = datetime.now(timezone.utc).isoformat()
        clean_detail = str(detail)[:500] if detail else None
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO vendor_verifications
                    (vendor, category, method, status, source, detail, latency_ms, verified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(vendor, category) DO UPDATE SET
                    method=excluded.method,
                    status=excluded.status,
                    source=excluded.source,
                    detail=excluded.detail,
                    latency_ms=excluded.latency_ms,
                    verified_at=excluded.verified_at
                """,
                (vendor, category, method, status, source, clean_detail, latency_ms, verified_at),
            )
        return self.get(vendor, category) or {}

    def get(self, vendor: str, category: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM vendor_verifications WHERE vendor=? AND category=?",
                (vendor, category),
            ).fetchone()
        return dict(row) if row else None

    def list_latest(self) -> dict[str, dict[str, dict[str, Any]]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM vendor_verifications ORDER BY verified_at DESC"
            ).fetchall()
        result: dict[str, dict[str, dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            result.setdefault(item["category"], {})[item["vendor"]] = item
        return result


vendor_verification_store = VendorVerificationStore()
