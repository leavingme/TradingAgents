"""SQLite-backed run store for TradingAgents Web UI.

Delegates core SQLite operations to tradingagents.runtime.history_store.
In-memory event queues are kept per-run so live SSE streaming works.
"""

from __future__ import annotations

import json
import os
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingagents.runtime import AnalysisEvent, history_store, DB_PATH
from .models import RunCreateRequest, RunStatus

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
    """Thread-safe run store delegating SQL persistence to core history_store."""

    def __init__(self, db_path: Path = DB_PATH):
        # Sync core history_store with the configured db_path
        history_store._db_path = db_path
        history_store._init_db()

        # In-memory cache: run_id -> RunRecord (for active + recently created runs)
        self._runs: dict[str, RunRecord] = {}
        self._lock = threading.RLock()
        
        # Recover any active runs left in running/pending state from a previous session
        history_store._recover_runs()

    def _dict_to_record(self, run_dict: dict[str, Any]) -> RunRecord:
        """Reconstruct a RunRecord from a history_store dictionary representation."""
        request = RunCreateRequest(
            ticker=run_dict["ticker"],
            analysis_date=run_dict["analysis_date"],
            asset_type=run_dict["asset_type"],
            selected_analysts=json.loads(run_dict["selected_analysts"]),
            llm_provider=run_dict["llm_provider"],
            research_depth=run_dict["research_depth"],
        )

        events: list[AnalysisEvent] = []
        for ev in run_dict.get("events", []):
            events.append(
                AnalysisEvent(
                    type=ev["type"],
                    run_id=run_dict["run_id"],
                    agent=ev["agent"],
                    content=ev["content"],
                    timestamp=ev["timestamp"],
                )
            )

        q: queue.Queue[AnalysisEvent | None] = queue.Queue()
        for ev in events:
            q.put(ev)
        q.put(None)  # sentinel

        return RunRecord(
            run_id=run_dict["run_id"],
            request=request,
            status=run_dict["status"],
            created_at=run_dict["created_at"],
            started_at=run_dict["started_at"],
            finished_at=run_dict["finished_at"],
            report_path=run_dict["report_path"],
            error=run_dict["error"],
            events=events,
            event_queue=q,
        )

    def create(self, run_id: str, request: RunCreateRequest) -> RunRecord:
        with self._lock:
            record = RunRecord(run_id=run_id, request=request)
            self._runs[run_id] = record

            history_store.create_run(
                run_id=run_id,
                ticker=request.ticker,
                analysis_date=str(request.analysis_date),
                asset_type=request.asset_type,
                selected_analysts=request.selected_analysts,
                llm_provider=request.llm_provider,
                research_depth=request.research_depth,
                status=record.status,
                created_at=record.created_at,
            )
            return record

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            # Fast path: in-memory cache
            if run_id in self._runs:
                return self._runs[run_id]

            # Slow path: load from DB via history_store
            run_dict = history_store.get_run(run_id)
            if run_dict is None:
                return None

            record = self._dict_to_record(run_dict)
            self._runs[run_id] = record
            return record

    def list(self) -> list[RunRecord]:
        """Return up to 100 runs ordered by created_at DESC, sourced from DB."""
        with self._lock:
            runs_list = history_store.list_runs(limit=100)
            result: list[RunRecord] = []
            for run_dict in runs_list:
                run_id = run_dict["run_id"]
                if run_id in self._runs:
                    result.append(self._runs[run_id])
                else:
                    full_run = history_store.get_run(run_id)
                    if full_run:
                        record = self._dict_to_record(full_run)
                        self._runs[run_id] = record
                        result.append(record)
            return result

    def mark_started(self, run_id: str) -> None:
        with self._lock:
            record = self._runs[run_id]
            record.status = "running"
            record.started_at = _now()

            history_store.mark_started(run_id, started_at=record.started_at)

    def add_event(self, run_id: str, event: AnalysisEvent) -> None:
        with self._lock:
            record = self._runs[run_id]
            event = _web_safe_event(event)
            record.events.append(event)

            # Update in-memory state derived from event type
            if event.type == "run_completed" and isinstance(event.content, dict):
                record.report_path = event.content.get("report_path")
            if event.type == "error" and record.status != "cancelled":
                record.status = "failed"
                if isinstance(event.content, dict):
                    record.error = event.content.get("error")

            # Persist event to DB via history_store
            history_store.add_event(run_id, event)

            # Push to live SSE queue
            record.event_queue.put(event)

    def mark_finished(self, run_id: str, status: RunStatus) -> None:
        with self._lock:
            record = self._runs[run_id]
            if record.status != "failed":
                record.status = status
            record.finished_at = _now()

            history_store.mark_finished(run_id, record.status, finished_at=record.finished_at)

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

            history_store.request_cancel(run_id)
            return True


# ---------------------------------------------------------------------------
# Module-level singleton used by the FastAPI app
# ---------------------------------------------------------------------------

store = TaskStore()


def _web_safe_event(event: AnalysisEvent) -> AnalysisEvent:
    """Trim runtime-only payloads before persisting/streaming through WebUI.

    ``run_completed`` from the headless runtime carries the full graph state so
    ``run_analysis_once()`` callers can inspect it. That state may contain
    LangChain messages or other non-JSON objects and is far too large/noisy for
    the Web API event log, which only needs the decision and report path.
    """

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
