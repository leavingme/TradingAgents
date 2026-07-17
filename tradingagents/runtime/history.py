"""Core runtime store to persist execution history and events to SQLite."""

import json
import math
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .events import AnalysisEvent
from tradingagents.sqlite_utils import configure_wal, connect_sqlite

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nonnegative_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        return None
    return int(value) if isinstance(value, int) else numeric


def _elapsed_seconds(started_at: Any, finished_at: Any) -> float | None:
    if not isinstance(started_at, str) or not isinstance(finished_at, str):
        return None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if started.tzinfo is None or finished.tzinfo is None:
        return None
    elapsed = (finished.astimezone(timezone.utc) - started.astimezone(timezone.utc)).total_seconds()
    return elapsed if math.isfinite(elapsed) and elapsed >= 0 else None


def _default_db_path() -> Path:
    configured = os.environ.get("TRADINGAGENTS_DB")
    if configured:
        return Path(configured)

    home_path = Path.home() / ".tradingagents" / "runs.db"
    fallback_path = Path.cwd() / ".tradingagents" / "runs.db"

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
        return connect_sqlite(self._db_path)

    def _init_db(self) -> None:
        with self._lock:
            with self._conn() as conn:
                configure_wal(conn)
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
                        decision_status   TEXT NOT NULL DEFAULT 'unavailable',
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
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS run_vendor_calls (
                        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id              TEXT NOT NULL,
                        call_id             TEXT NOT NULL,
                        attempt             INTEGER NOT NULL,
                        category            TEXT NOT NULL,
                        method              TEXT NOT NULL,
                        vendor              TEXT NOT NULL,
                        agent               TEXT,
                        symbol              TEXT,
                        status              TEXT NOT NULL,
                        selected            INTEGER NOT NULL DEFAULT 0,
                        arguments_json      TEXT,
                        latency_ms          INTEGER,
                        error_type          TEXT,
                        error_detail        TEXT,
                        result_summary      TEXT,
                        result_hash         TEXT,
                        calculation_start   TEXT,
                        requested_end       TEXT,
                        data_latest_date    TEXT,
                        started_at          TEXT NOT NULL,
                        finished_at         TEXT NOT NULL,
                        FOREIGN KEY (run_id) REFERENCES runs(run_id),
                        UNIQUE (run_id, call_id, attempt)
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS decision_evaluations (
                        run_id                TEXT NOT NULL,
                        horizon_sessions      INTEGER NOT NULL,
                        evaluated_by_run_id   TEXT,
                        ticker                TEXT NOT NULL,
                        analysis_date         TEXT NOT NULL,
                        rating                TEXT NOT NULL,
                        benchmark             TEXT NOT NULL,
                        entry_date            TEXT,
                        exit_date             TEXT,
                        stock_entry_close      REAL,
                        stock_exit_close       REAL,
                        benchmark_entry_close  REAL,
                        benchmark_exit_close   REAL,
                        stock_entry_source_id  TEXT,
                        stock_exit_source_id   TEXT,
                        benchmark_entry_source_id TEXT,
                        benchmark_exit_source_id  TEXT,
                        raw_return            REAL NOT NULL,
                        benchmark_return      REAL NOT NULL,
                        alpha_return          REAL NOT NULL,
                        exposure              REAL NOT NULL,
                        directional_hit       INTEGER NOT NULL,
                        score                 REAL NOT NULL,
                        architecture_version  TEXT NOT NULL,
                        architecture_fingerprint TEXT NOT NULL DEFAULT 'legacy-unspecified',
                        evaluated_at          TEXT NOT NULL,
                        PRIMARY KEY (run_id, horizon_sessions),
                        FOREIGN KEY (run_id) REFERENCES runs(run_id)
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_run_vendor_calls_run "
                    "ON run_vendor_calls(run_id, id)"
                )
                existing_columns = {
                    row["name"] for row in conn.execute("PRAGMA table_info(run_vendor_calls)")
                }
                run_columns = {
                    row["name"] for row in conn.execute("PRAGMA table_info(runs)")
                }
                if "decision_status" not in run_columns:
                    conn.execute(
                        "ALTER TABLE runs ADD COLUMN decision_status "
                        "TEXT NOT NULL DEFAULT 'unavailable'"
                    )
                if "architecture_version" not in run_columns:
                    conn.execute(
                        "ALTER TABLE runs ADD COLUMN architecture_version "
                        "TEXT NOT NULL DEFAULT 'legacy'"
                    )
                if "architecture_fingerprint" not in run_columns:
                    conn.execute(
                        "ALTER TABLE runs ADD COLUMN architecture_fingerprint "
                        "TEXT NOT NULL DEFAULT 'legacy-unspecified'"
                    )
                if "architecture_manifest_json" not in run_columns:
                    conn.execute(
                        "ALTER TABLE runs ADD COLUMN architecture_manifest_json TEXT"
                    )
                evaluation_columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(decision_evaluations)")
                }
                if "architecture_fingerprint" not in evaluation_columns:
                    conn.execute(
                        "ALTER TABLE decision_evaluations ADD COLUMN "
                        "architecture_fingerprint TEXT NOT NULL "
                        "DEFAULT 'legacy-unspecified'"
                    )
                for column in (
                    "entry_date TEXT",
                    "exit_date TEXT",
                    "stock_entry_close REAL",
                    "stock_exit_close REAL",
                    "benchmark_entry_close REAL",
                    "benchmark_exit_close REAL",
                    "stock_entry_source_id TEXT",
                    "stock_exit_source_id TEXT",
                    "benchmark_entry_source_id TEXT",
                    "benchmark_exit_source_id TEXT",
                ):
                    name = column.split()[0]
                    if name not in evaluation_columns:
                        conn.execute(
                            f"ALTER TABLE decision_evaluations ADD COLUMN {column}"
                        )
                for column in (
                    "symbol TEXT",
                    "agent TEXT",
                    "calculation_start TEXT",
                    "requested_end TEXT",
                    "data_latest_date TEXT",
                ):
                    name = column.split()[0]
                    if name not in existing_columns:
                        conn.execute(f"ALTER TABLE run_vendor_calls ADD COLUMN {column}")

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
        architecture_version: str = "legacy",
        architecture_fingerprint: str = "legacy-unspecified",
        architecture_manifest_json: str | None = None,
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
                         status, created_at, architecture_version,
                         architecture_fingerprint, architecture_manifest_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        architecture_version,
                        architecture_fingerprint,
                        architecture_manifest_json,
                    ),
                )
                conn.execute(
                    """
                    UPDATE runs
                    SET architecture_version=?, architecture_fingerprint=?,
                        architecture_manifest_json=COALESCE(?, architecture_manifest_json)
                    WHERE run_id=?
                    """,
                    (
                        architecture_version,
                        architecture_fingerprint,
                        architecture_manifest_json,
                        run_id,
                    ),
                )

    def find_runs(
        self,
        *,
        ticker: str,
        analysis_date: str,
        decision_status: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM runs WHERE UPPER(ticker)=? AND analysis_date=?"
        params: list[Any] = [ticker.upper(), str(analysis_date)]
        if decision_status is not None:
            query += " AND decision_status=?"
            params.append(decision_status)
        query += " ORDER BY created_at DESC"
        with self._lock:
            with self._conn() as conn:
                return [dict(row) for row in conn.execute(query, params).fetchall()]

    def update_run_architecture(
        self,
        run_id: str,
        *,
        architecture_version: str,
        architecture_fingerprint: str,
        architecture_manifest_json: str,
    ) -> None:
        """Replace preliminary identity with the effective runtime manifest."""
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """
                    UPDATE runs
                    SET architecture_version=?, architecture_fingerprint=?,
                        architecture_manifest_json=?
                    WHERE run_id=?
                    """,
                    (
                        architecture_version,
                        architecture_fingerprint,
                        architecture_manifest_json,
                        run_id,
                    ),
                )

    def add_decision_evaluation(self, record: dict[str, Any]) -> None:
        """Persist one immutable fixed-horizon outcome for an analyzed run."""
        required_provenance = (
            "entry_date",
            "exit_date",
            "stock_entry_source_id",
            "stock_exit_source_id",
            "benchmark_entry_source_id",
            "benchmark_exit_source_id",
        )
        missing = [field for field in required_provenance if not record.get(field)]
        if missing:
            raise ValueError(
                "decision evaluation lacks audited provenance: " + ", ".join(missing)
            )
        entry_date = datetime.fromisoformat(str(record["entry_date"])).date()
        exit_date = datetime.fromisoformat(str(record["exit_date"])).date()
        if exit_date <= entry_date:
            raise ValueError("decision evaluation exit_date must follow entry_date")
        for field in required_provenance[2:]:
            if not str(record[field]).startswith("ohlcv:"):
                raise ValueError(f"decision evaluation {field} is not an OHLCV source ID")
        numeric_fields = (
            "stock_entry_close",
            "stock_exit_close",
            "benchmark_entry_close",
            "benchmark_exit_close",
            "raw_return",
            "benchmark_return",
            "alpha_return",
            "exposure",
            "score",
        )
        for field in numeric_fields:
            value = float(record[field])
            if not math.isfinite(value):
                raise ValueError(f"decision evaluation {field} must be finite")
            if field.endswith("_close") and value <= 0:
                raise ValueError(f"decision evaluation {field} must be positive")
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO decision_evaluations (
                        run_id, horizon_sessions, evaluated_by_run_id, ticker,
                        analysis_date, rating, benchmark,
                        entry_date, exit_date, stock_entry_close, stock_exit_close,
                        benchmark_entry_close, benchmark_exit_close,
                        stock_entry_source_id, stock_exit_source_id,
                        benchmark_entry_source_id, benchmark_exit_source_id,
                        raw_return,
                        benchmark_return, alpha_return, exposure,
                        directional_hit, score, architecture_version,
                        architecture_fingerprint, evaluated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["run_id"], record["horizon_sessions"],
                        record.get("evaluated_by_run_id"), record["ticker"],
                        record["analysis_date"], record["rating"], record["benchmark"],
                        record.get("entry_date"), record.get("exit_date"),
                        record.get("stock_entry_close"), record.get("stock_exit_close"),
                        record.get("benchmark_entry_close"),
                        record.get("benchmark_exit_close"),
                        record.get("stock_entry_source_id"),
                        record.get("stock_exit_source_id"),
                        record.get("benchmark_entry_source_id"),
                        record.get("benchmark_exit_source_id"),
                        record["raw_return"], record["benchmark_return"],
                        record["alpha_return"], record["exposure"],
                        int(bool(record["directional_hit"])), record["score"],
                        record["architecture_version"],
                        record.get("architecture_fingerprint", "legacy-unspecified"),
                        record.get("evaluated_at") or _now(),
                    ),
                )

    def list_decision_evaluations(
        self,
        *,
        ticker: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT decision_evaluations.*, "
            "runs.started_at AS run_started_at, runs.finished_at AS run_finished_at "
            "FROM decision_evaluations "
            "LEFT JOIN runs ON runs.run_id=decision_evaluations.run_id"
        )
        params: list[Any] = []
        if ticker is not None:
            query += " WHERE UPPER(decision_evaluations.ticker)=?"
            params.append(ticker.upper())
        query += " ORDER BY decision_evaluations.evaluated_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            with self._conn() as conn:
                rows = [dict(row) for row in conn.execute(query, params).fetchall()]
                if not rows:
                    return rows
                run_ids = list(dict.fromkeys(str(row["run_id"]) for row in rows))
                stats_rows: list[sqlite3.Row] = []
                for offset in range(0, len(run_ids), 500):
                    batch = run_ids[offset : offset + 500]
                    placeholders = ",".join("?" for _ in batch)
                    stats_rows.extend(
                        conn.execute(
                            f"""
                            SELECT events.run_id, events.content
                            FROM events
                            JOIN (
                                SELECT run_id, MAX(id) AS latest_id
                                FROM events
                                WHERE event_type='stats' AND run_id IN ({placeholders})
                                GROUP BY run_id
                            ) latest ON latest.latest_id=events.id
                            """,
                            batch,
                        ).fetchall()
                    )
        final_stats: dict[str, dict[str, Any]] = {}
        for stats_row in stats_rows:
            try:
                payload = json.loads(stats_row["content"] or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(payload, dict):
                final_stats[str(stats_row["run_id"])] = payload
        for row in rows:
            row["runtime_seconds"] = _elapsed_seconds(
                row.pop("run_started_at", None), row.pop("run_finished_at", None)
            )
            stats = final_stats.get(str(row["run_id"]), {})
            for field in ("llm_calls", "tool_calls", "tokens_in", "tokens_out"):
                row[field] = _nonnegative_number(stats.get(field))
        return rows

    def get_longitudinal_context(
        self,
        ticker: str,
        *,
        information_cutoff: str | None = None,
        same_symbol_limit: int = 10,
        cross_symbol_limit: int = 5,
    ) -> str:
        """Render compact audited outcomes for downstream decision agents.

        Only deterministic fields from ``decision_evaluations`` are exposed;
        LLM-written Markdown reflections are deliberately excluded. Historical
        point-in-time callers may provide a cutoff so outcomes evaluated later
        cannot leak into the reconstructed run.
        """
        from tradingagents.evaluation import architecture_rollups

        cutoff = None
        if information_cutoff:
            cutoff = datetime.fromisoformat(information_cutoff.replace("Z", "+00:00"))
            if cutoff.tzinfo is None or cutoff.utcoffset() is None:
                raise ValueError("information_cutoff must include a timezone")
            cutoff = cutoff.astimezone(timezone.utc)

        rows = self.list_decision_evaluations(limit=5000)
        visible: list[dict[str, Any]] = []
        for row in rows:
            evaluated_at = datetime.fromisoformat(
                str(row["evaluated_at"]).replace("Z", "+00:00")
            )
            if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
                evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)
            if cutoff is not None and evaluated_at.astimezone(timezone.utc) > cutoff:
                continue
            visible.append(row)

        normalized_ticker = ticker.upper()
        same = [row for row in visible if str(row["ticker"]).upper() == normalized_ticker][
            :same_symbol_limit
        ]
        cross = [row for row in visible if str(row["ticker"]).upper() != normalized_ticker][
            :cross_symbol_limit
        ]
        selected = [*same, *cross]
        if not selected:
            return ""

        fields = (
            "run_id",
            "ticker",
            "analysis_date",
            "rating",
            "horizon_sessions",
            "benchmark",
            "entry_date",
            "exit_date",
            "stock_entry_close",
            "stock_exit_close",
            "benchmark_entry_close",
            "benchmark_exit_close",
            "stock_entry_source_id",
            "stock_exit_source_id",
            "benchmark_entry_source_id",
            "benchmark_exit_source_id",
            "raw_return",
            "benchmark_return",
            "alpha_return",
            "exposure",
            "directional_hit",
            "score",
            "architecture_version",
            "architecture_fingerprint",
            "evaluated_at",
        )
        payload = {
            "schema": "tradingagents/audited-longitudinal-outcomes/v1",
            "interpretation": (
                "Historical calibration evidence only. Outcomes do not prove causality, "
                "may come from a different market regime, and cannot authorize trade levels."
            ),
            "same_symbol_outcomes": [
                {key: (bool(row[key]) if key == "directional_hit" else row[key]) for key in fields}
                for row in same
            ],
            "cross_symbol_outcomes": [
                {key: (bool(row[key]) if key == "directional_hit" else row[key]) for key in fields}
                for row in cross
            ],
            "architecture_rollups": architecture_rollups(selected),
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

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
                decision_status = None
                if event.type == "run_completed" and isinstance(event.content, dict):
                    decision_status = event.content.get("decision_status", "unavailable")
                    status = (
                        "completed" if decision_status == "validated" else decision_status
                    )
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
                        error=COALESCE(?, error),
                        decision_status=COALESCE(?, decision_status)
                    WHERE run_id=?
                    """,
                    (cnt, status, status, report_path, error, decision_status, run_id),
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

    def add_vendor_call(self, record: dict[str, Any]) -> None:
        """Append one immutable vendor attempt to a run's audit ledger."""
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO run_vendor_calls (
                        run_id, call_id, attempt, category, method, vendor, agent, symbol,
                        status, selected, arguments_json, latency_ms,
                        error_type, error_detail, result_summary, result_hash,
                        calculation_start, requested_end, data_latest_date,
                        started_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["run_id"], record["call_id"], record["attempt"],
                        record["category"], record["method"], record["vendor"],
                        record.get("agent"),
                        record.get("symbol"),
                        record["status"], int(bool(record.get("selected"))),
                        record.get("arguments_json"), record.get("latency_ms"),
                        record.get("error_type"), record.get("error_detail"),
                        record.get("result_summary"), record.get("result_hash"),
                        record.get("calculation_start"), record.get("requested_end"),
                        record.get("data_latest_date"),
                        record["started_at"], record["finished_at"],
                    ),
                )

    def get_vendor_calls(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM run_vendor_calls WHERE run_id=? ORDER BY id",
                    (run_id,),
                ).fetchall()
                return [dict(row) for row in rows]

    def get_vendor_summary(self, run_id: str) -> dict[str, Any]:
        """Build a deterministic, replay-safe summary of a run's vendor paths."""
        return summarize_vendor_calls(self.get_vendor_calls(run_id))

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
                run_dict["vendor_summary"] = self.get_vendor_summary(run_id)
                run_dict["data_status"] = run_dict["vendor_summary"]["data_status"]
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
                if row["status"] in (
                    "completed", "review_required", "unavailable", "failed", "cancelled"
                ):
                    return True
                conn.execute(
                    "UPDATE runs SET status='cancelled' WHERE run_id=?", (run_id,)
                )
                return True

    def delete_run(self, run_id: str) -> bool:
        with self._lock:
            with self._conn() as conn:
                row = conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone()
                if not row:
                    return False
                conn.execute("DELETE FROM events WHERE run_id=?", (run_id,))
                conn.execute("DELETE FROM run_vendor_calls WHERE run_id=?", (run_id,))
                conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
                return True

    def clear_all_runs(self) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute("DELETE FROM events")
                conn.execute("DELETE FROM run_vendor_calls")
                conn.execute("DELETE FROM runs")

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

def summarize_vendor_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        grouped.setdefault(str(call["call_id"]), []).append(call)

    trajectories: list[dict[str, Any]] = []
    for call_id, attempts in grouped.items():
        attempts.sort(key=lambda item: int(item.get("attempt") or 0))
        selected = next((item for item in attempts if item.get("selected")), None)
        if selected is None:
            # Financial reconciliation records validated supporting statements
            # as independent, non-selected calls before selecting the outer
            # requested result. Do not turn an all-success supporting trajectory
            # into a false unavailable domain merely because it is not itself
            # the router's selected return value.
            success_statuses = {"available", "cache_hit"}
            status = (
                "available"
                if attempts and all(
                    str(item.get("status")) in success_statuses for item in attempts
                )
                else "unavailable"
            )
        elif len(attempts) > 1 or int(selected.get("attempt") or 0) > 1:
            status = "degraded"
        else:
            status = "available"
        first = attempts[0]
        attempt_details = [
            {
                "attempt": int(item.get("attempt") or 0),
                "vendor": item.get("vendor"),
                "status": item.get("status"),
                "selected": bool(item.get("selected")),
                "error_type": item.get("error_type"),
                "error_detail": item.get("error_detail"),
            }
            for item in attempts
        ]
        trajectories.append({
            "call_id": call_id,
            "category": first.get("category"),
            "method": first.get("method"),
            "agent": first.get("agent"),
            "symbol": first.get("symbol"),
            "status": status,
            "selected_vendor": selected.get("vendor") if selected else None,
            "attempt_count": len(attempts),
            "attempts": attempt_details,
        })

    statuses = {item["status"] for item in trajectories}
    if not trajectories:
        data_status = "not_observed"
    elif statuses == {"available"}:
        data_status = "available"
    elif statuses == {"unavailable"}:
        data_status = "unavailable"
    else:
        data_status = "degraded"

    domain_statuses: dict[str, set[str]] = {}
    for item in trajectories:
        domain_statuses.setdefault(str(item["category"]), set()).add(item["status"])

    return {
        "data_status": data_status,
        "call_count": len(trajectories),
        "attempt_count": len(calls),
        "fallback_domains": sorted({
            str(item["category"]) for item in trajectories
            if item["status"] == "degraded"
        }),
        # A domain is unavailable only when every requested trajectory in that
        # domain failed. Mixed successful/failed calls are partial evidence,
        # not an unavailable provider domain.
        "partially_available_domains": sorted(
            category for category, category_statuses in domain_statuses.items()
            if "unavailable" in category_statuses
            and category_statuses != {"unavailable"}
        ),
        "unavailable_domains": sorted(
            category for category, category_statuses in domain_statuses.items()
            if category_statuses == {"unavailable"}
        ),
        # Healthy first-attempt calls stay available in the append-only ledger
        # and vendor_attempt events. Keep the run summary focused on paths that
        # require operator attention so list/history responses remain compact.
        "trajectories": [
            item for item in trajectories if item["status"] != "available"
        ],
    }


history_store = RunHistoryStore()
