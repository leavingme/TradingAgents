"""Core runtime store to persist execution history and events to SQLite."""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .events import AnalysisEvent

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _default_db_path() -> Path:
    configured = os.environ.get("TRADINGAGENTS_DB") or os.environ.get("TRADINGAGENTS_WEBUI_DB")
    if configured:
        return Path(configured)

    home_path = Path.home() / ".tradingagents" / "webui_runs.db"
    fallback_path = Path.cwd() / ".tradingagents" / "webui_runs.db"

    try:
        home_path.parent.mkdir(parents=True, exist_ok=True)
        probe_path = home_path.parent / ".write_test"
        with probe_path.open("w", encoding="utf-8") as probe:
            probe.write("")
        probe_path.unlink(missing_ok=True)
        return home_path
    except OSError:
        return fallback_path

DB_PATH = _default_db_path()

class RunHistoryStore:
    """Core runtime store to persist execution history and events to SQLite."""

    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
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

    def create_run(
        self,
        run_id: str,
        ticker: str,
        analysis_date: str,
        asset_type: str,
        selected_analysts: list[str] | tuple[str, ...],
        llm_provider: str | None,
        research_depth: int | None,
        status: str = "pending",
        created_at: str | None = None,
    ) -> None:
        with self._lock:
            if not created_at:
                created_at = _now()
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO runs
                        (run_id, ticker, analysis_date, asset_type,
                         selected_analysts, llm_provider, research_depth,
                         status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        ticker,
                        str(analysis_date),
                        asset_type,
                        json.dumps(list(selected_analysts)),
                        llm_provider,
                        research_depth,
                        status,
                        created_at,
                    ),
                )

    def mark_started(self, run_id: str, started_at: str | None = None) -> None:
        with self._lock:
            if not started_at:
                started_at = _now()
            with self._conn() as conn:
                conn.execute(
                    "UPDATE runs SET status='running', started_at=? WHERE run_id=?",
                    (started_at, run_id),
                )

    def add_event(self, run_id: str, event: AnalysisEvent) -> None:
        with self._lock:
            # Clean runtime-only data to keep DB small and serializable
            event = _safe_db_event(event)

            timestamp = getattr(event, "timestamp", None) or _now()
            content_json = (
                json.dumps(event.content, default=str) if event.content is not None else None
            )

            with self._conn() as conn:
                # Deduplicate events to prevent double-writing in Web UI process
                dup = conn.execute(
                    """
                    SELECT 1 FROM events
                    WHERE run_id=? AND event_type=? AND COALESCE(agent, '')=COALESCE(?, '')
                      AND COALESCE(content, '')=COALESCE(?, '') AND timestamp=?
                    """,
                    (run_id, event.type, event.agent, content_json, timestamp)
                ).fetchone()
                if dup:
                    return

                conn.execute(
                    "INSERT INTO events (run_id, event_type, agent, content, timestamp)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (run_id, event.type, event.agent, content_json, timestamp),
                )
                
                # Fetch current count
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM events WHERE run_id=?", (run_id,)
                ).fetchone()
                cnt = row["cnt"] if row else 0

                # Derived values
                status = "running"
                report_path = None
                error = None
                if event.type == "run_completed" and isinstance(event.content, dict):
                    status = "completed"
                    report_path = event.content.get("report_path")
                elif event.type == "error":
                    status = "failed"
                    if isinstance(event.content, dict):
                        error = event.content.get("error")

                conn.execute(
                    """
                    UPDATE runs
                    SET event_count=?,
                        status=CASE WHEN ? = 'running' THEN status ELSE ? END,
                        report_path=COALESCE(?, report_path),
                        error=COALESCE(?, error)
                    WHERE run_id=?
                    """,
                    (cnt, status, status, report_path, error, run_id),
                )

    def mark_finished(self, run_id: str, status: str, finished_at: str | None = None) -> None:
        with self._lock:
            if not finished_at:
                finished_at = _now()
            with self._conn() as conn:
                conn.execute(
                    "UPDATE runs SET status=?, finished_at=? WHERE run_id=?",
                    (status, finished_at, run_id),
                )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM runs WHERE run_id=?", (run_id,)
                ).fetchone()
                if not row:
                    return None
                run_dict = dict(row)
                
                # Load events
                ev_rows = conn.execute(
                    "SELECT event_type, agent, content, timestamp FROM events"
                    " WHERE run_id=? ORDER BY id",
                    (run_id,),
                ).fetchall()
                
                events = []
                for ev in ev_rows:
                    content = json.loads(ev["content"]) if ev["content"] else None
                    events.append({
                        "type": ev["event_type"],
                        "run_id": run_id,
                        "agent": ev["agent"],
                        "content": content,
                        "timestamp": ev["timestamp"],
                    })
                run_dict["events"] = events
                return run_dict

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(row) for row in rows]

    def request_cancel(self, run_id: str) -> bool:
        with self._lock:
            with self._conn() as conn:
                row = conn.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
                if not row:
                    return False
                if row["status"] in ("completed", "failed", "cancelled"):
                    return True
                conn.execute(
                    "UPDATE runs SET status='cancelled' WHERE run_id=?", (run_id,)
                )
                return True

    def _recover_runs(self) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE runs SET status='failed', error='server restarted',"
                    " finished_at=? WHERE status IN ('running', 'pending')",
                    (_now(),),
                )

def _safe_db_event(event: AnalysisEvent) -> AnalysisEvent:
    if event.type != "run_completed" or not isinstance(event.content, dict):
        return event
    if "final_state" not in event.content:
        return event
    content = dict(event.content)
    content.pop("final_state", None)
    return AnalysisEvent(
        type=event.type,
        run_id=event.run_id,
        timestamp=event.timestamp,
        agent=event.agent,
        content=content,
    )

history_store = RunHistoryStore()
