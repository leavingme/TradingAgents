"""SQLite-backed run store for TradingAgents Web UI.

Persists runs and events to ~/.tradingagents/webui_runs.db (or the path
specified by the TRADINGAGENTS_WEBUI_DB environment variable).  In-memory
event queues are kept per-run so live SSE streaming works without touching
the DB on every event read; past-run event replay reads directly from the
events table.
"""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingagents.runtime import AnalysisEvent

from .models import RunCreateRequest, RunStatus

# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------

DB_PATH = Path(
    os.environ.get(
        "TRADINGAGENTS_WEBUI_DB",
        Path.home() / ".tradingagents" / "webui_runs.db",
    )
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# RunRecord dataclass
# ---------------------------------------------------------------------------


@dataclass
class RunRecord:
    run_id: str
    request: RunCreateRequest
    status: RunStatus = "pending"
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    report_path: str | None = None
    error: str | None = None
    events: list[AnalysisEvent] = field(default_factory=list)
    event_queue: queue.Queue[AnalysisEvent | None] = field(
        default_factory=queue.Queue
    )
    cancel_requested: bool = False

    def to_response(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "ticker": self.request.ticker,
            "analysis_date": str(self.request.analysis_date),
            "asset_type": self.request.asset_type,
            "selected_analysts": list(self.request.selected_analysts),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "report_path": self.report_path,
            "error": self.error,
            "event_count": len(self.events),
        }


# ---------------------------------------------------------------------------
# TaskStore
# ---------------------------------------------------------------------------


class TaskStore:
    """Thread-safe run store backed by SQLite with in-memory SSE queues."""

    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        # In-memory cache: run_id -> RunRecord (for active + recently created runs)
        self._runs: dict[str, RunRecord] = {}
        self._lock = threading.RLock()
        self._init_db()
        self._recover_runs()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id            TEXT PRIMARY KEY,
                    ticker            TEXT NOT NULL,
                    analysis_date     TEXT NOT NULL,
                    asset_type        TEXT NOT NULL,
                    selected_analysts TEXT NOT NULL,
                    llm_provider      TEXT,
                    research_depth    INTEGER,
                    status            TEXT NOT NULL DEFAULT 'pending',
                    created_at        TEXT NOT NULL,
                    started_at        TEXT,
                    finished_at       TEXT,
                    report_path       TEXT,
                    error             TEXT,
                    event_count       INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id     TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    agent      TEXT,
                    content    TEXT,
                    timestamp  TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
            """)

    def _recover_runs(self) -> None:
        """Mark any run left in running/pending state (from a previous server
        session) as failed so clients don't wait forever."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET status='failed', error='server restarted',"
                " finished_at=? WHERE status IN ('running', 'pending')",
                (_now(),),
            )

    # ------------------------------------------------------------------
    # Row → RunRecord reconstruction
    # ------------------------------------------------------------------

    def _row_to_record(self, row: sqlite3.Row) -> RunRecord:
        """Reconstruct a RunRecord from a DB row.

        Events are loaded from the events table so replay works for finished
        runs.  A sentinel (None) is pre-loaded into the event_queue so any
        SSE consumer exits cleanly instead of blocking forever.
        """
        request = RunCreateRequest(
            ticker=row["ticker"],
            analysis_date=row["analysis_date"],
            asset_type=row["asset_type"],
            selected_analysts=json.loads(row["selected_analysts"]),
            llm_provider=row["llm_provider"],
            research_depth=row["research_depth"],
        )

        # Load persisted events
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT event_type, agent, content, timestamp FROM events"
                " WHERE run_id=? ORDER BY id",
                (row["run_id"],),
            ).fetchall()

        events: list[AnalysisEvent] = []
        for ev_row in rows:
            content = json.loads(ev_row["content"]) if ev_row["content"] else None
            events.append(
                AnalysisEvent(
                    type=ev_row["event_type"],
                    agent=ev_row["agent"],
                    content=content,
                    timestamp=ev_row["timestamp"],
                )
            )

        # Pre-load a sentinel so SSE consumers don't block on finished runs
        q: queue.Queue[AnalysisEvent | None] = queue.Queue()
        for ev in events:
            q.put(ev)
        q.put(None)  # sentinel

        return RunRecord(
            run_id=row["run_id"],
            request=request,
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            report_path=row["report_path"],
            error=row["error"],
            events=events,
            event_queue=q,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self, run_id: str, request: RunCreateRequest) -> RunRecord:
        with self._lock:
            record = RunRecord(run_id=run_id, request=request)
            self._runs[run_id] = record

            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO runs
                        (run_id, ticker, analysis_date, asset_type,
                         selected_analysts, llm_provider, research_depth,
                         status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        request.ticker,
                        str(request.analysis_date),
                        request.asset_type,
                        json.dumps(list(request.selected_analysts)),
                        request.llm_provider,
                        request.research_depth,
                        record.status,
                        record.created_at,
                    ),
                )
            return record

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            # Fast path: in-memory cache
            if run_id in self._runs:
                return self._runs[run_id]

            # Slow path: load from DB
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM runs WHERE run_id=?", (run_id,)
                ).fetchone()

            if row is None:
                return None

            record = self._row_to_record(row)
            self._runs[run_id] = record
            return record

    def list(self) -> list[RunRecord]:
        """Return up to 100 runs ordered by created_at DESC, sourced from DB."""
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM runs ORDER BY created_at DESC LIMIT 100"
                ).fetchall()

            result: list[RunRecord] = []
            for row in rows:
                run_id = row["run_id"]
                if run_id in self._runs:
                    result.append(self._runs[run_id])
                else:
                    record = self._row_to_record(row)
                    self._runs[run_id] = record
                    result.append(record)
            return result

    def mark_started(self, run_id: str) -> None:
        with self._lock:
            record = self._runs[run_id]
            record.status = "running"
            record.started_at = _now()

            with self._conn() as conn:
                conn.execute(
                    "UPDATE runs SET status='running', started_at=? WHERE run_id=?",
                    (record.started_at, run_id),
                )

    def add_event(self, run_id: str, event: AnalysisEvent) -> None:
        with self._lock:
            record = self._runs[run_id]
            record.events.append(event)

            # Update in-memory state derived from event type
            if event.type == "run_completed" and isinstance(event.content, dict):
                record.report_path = event.content.get("report_path")
            if event.type == "error":
                record.status = "failed"
                if isinstance(event.content, dict):
                    record.error = event.content.get("error")

            # Persist event to DB
            timestamp = getattr(event, "timestamp", None) or _now()
            content_json = (
                json.dumps(event.content) if event.content is not None else None
            )

            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO events (run_id, event_type, agent, content, timestamp)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (run_id, event.type, event.agent, content_json, timestamp),
                )
                # Update derived columns on the runs row
                conn.execute(
                    "UPDATE runs SET event_count=?, report_path=COALESCE(?, report_path),"
                    " error=COALESCE(?, error), status=? WHERE run_id=?",
                    (
                        len(record.events),
                        record.report_path,
                        record.error,
                        record.status,
                        run_id,
                    ),
                )

            # Push to live SSE queue
            record.event_queue.put(event)

    def mark_finished(self, run_id: str, status: RunStatus) -> None:
        with self._lock:
            record = self._runs[run_id]
            if record.status != "failed":
                record.status = status
            record.finished_at = _now()

            with self._conn() as conn:
                conn.execute(
                    "UPDATE runs SET status=?, finished_at=? WHERE run_id=?",
                    (record.status, record.finished_at, run_id),
                )

            # Sentinel signals SSE consumer to close the stream
            record.event_queue.put(None)

    def request_cancel(self, run_id: str) -> bool:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                # Try to load from DB (may be a historical run)
                record = self.get(run_id)
            if record is None:
                return False
            if record.status in ("completed", "failed", "cancelled"):
                return True
            record.cancel_requested = True
            record.status = "cancelled"

            with self._conn() as conn:
                conn.execute(
                    "UPDATE runs SET status='cancelled' WHERE run_id=?",
                    (run_id,),
                )
            return True


# ---------------------------------------------------------------------------
# Module-level singleton used by the FastAPI app
# ---------------------------------------------------------------------------

store = TaskStore()
