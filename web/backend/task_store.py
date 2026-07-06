"""In-memory run store for the first Web API vertical slice."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from tradingagents.runtime import AnalysisEvent

from .models import RunCreateRequest, RunStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    event_queue: queue.Queue[AnalysisEvent | None] = field(default_factory=queue.Queue)
    cancel_requested: bool = False

    def to_response(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "ticker": self.request.ticker,
            "analysis_date": self.request.analysis_date,
            "asset_type": self.request.asset_type,
            "selected_analysts": self.request.selected_analysts,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "report_path": self.report_path,
            "error": self.error,
            "event_count": len(self.events),
        }


class TaskStore:
    def __init__(self):
        self._runs: dict[str, RunRecord] = {}
        self._lock = threading.RLock()

    def create(self, run_id: str, request: RunCreateRequest) -> RunRecord:
        with self._lock:
            record = RunRecord(run_id=run_id, request=request)
            self._runs[run_id] = record
            return record

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def mark_started(self, run_id: str) -> None:
        with self._lock:
            record = self._runs[run_id]
            record.status = "running"
            record.started_at = _now()

    def add_event(self, run_id: str, event: AnalysisEvent) -> None:
        with self._lock:
            record = self._runs[run_id]
            record.events.append(event)
            if event.type == "run_completed" and isinstance(event.content, dict):
                record.report_path = event.content.get("report_path")
            if event.type == "error":
                record.status = "failed"
                if isinstance(event.content, dict):
                    record.error = event.content.get("error")
            record.event_queue.put(event)

    def mark_finished(self, run_id: str, status: RunStatus) -> None:
        with self._lock:
            record = self._runs[run_id]
            if record.status != "failed":
                record.status = status
            record.finished_at = _now()
            record.event_queue.put(None)

    def request_cancel(self, run_id: str) -> bool:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return False
            if record.status in ("completed", "failed", "cancelled"):
                return True
            record.cancel_requested = True
            record.status = "cancelled"
            return True


store = TaskStore()
