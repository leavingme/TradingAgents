"""SQLite-backed run store for TradingAgents Web UI.

Delegates core SQLite operations to tradingagents.runtime.history_store.
In-memory event queues are kept per-run so live SSE streaming works.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingagents.runtime import AnalysisEvent, history_store, runtime_error_status
from tradingagents.architecture import AGENT_ARCHITECTURE_VERSION
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
    decision_status: str = "unavailable"
    market_data_date: str | None = None
    data_status: str = "not_observed"
    vendor_summary: dict[str, Any] = field(default_factory=dict)
    events: list[AnalysisEvent] = field(default_factory=list)
    cancel_requested: bool = False

    def to_response(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "ticker": self.request.ticker,
            "analysis_date": str(self.request.analysis_date),
            "market_data_date": self.market_data_date,
            "asset_type": self.request.asset_type,
            "selected_analysts": list(self.request.selected_analysts),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "report_path": self.report_path,
            "error": self.error,
            "decision_status": self.decision_status,
            "data_status": self.data_status,
            "vendor_summary": self.vendor_summary,
            "event_count": len(self.events),
        }


# ---------------------------------------------------------------------------
# TaskStore
# ---------------------------------------------------------------------------


class TaskStore:
    """Thread-safe run store delegating SQL persistence to core history_store."""

    def __init__(self, db_path: Path | None = None):
        db_path = db_path or Path(
            os.environ.get("TRADINGAGENTS_DB", str(history_store._db_path))
        )
        # Sync core history_store with the configured db_path
        history_store._db_path = db_path
        history_store._init_db()

        # In-memory cache: run_id -> RunRecord (for active + recently created runs)
        self._runs: dict[str, RunRecord] = {}
        self._lock = threading.RLock()
        self._event_condition = threading.Condition(self._lock)
        
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

        return RunRecord(
            run_id=run_dict["run_id"],
            request=request,
            status=run_dict["status"],
            created_at=run_dict["created_at"],
            started_at=run_dict["started_at"],
            finished_at=run_dict["finished_at"],
            report_path=run_dict["report_path"],
            error=run_dict["error"],
            decision_status=(
                run_dict.get("decision_status")
                or (
                    "market_data_pending"
                    if run_dict.get("status") == "market_data_pending"
                    else "unavailable"
                )
            ),
            market_data_date=run_dict.get("market_data_date"),
            data_status=run_dict.get("data_status", "not_observed"),
            vendor_summary=run_dict.get("vendor_summary", {}),
            events=events,
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
                architecture_version=AGENT_ARCHITECTURE_VERSION,
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

    def add_event(
        self, run_id: str, event: AnalysisEvent, *, persist: bool = True
    ) -> None:
        with self._lock:
            record = self._runs[run_id]
            event = _web_safe_event(event)
            record.events.append(event)

            # Update in-memory state derived from event type
            if event.type == "market_data_status" and isinstance(event.content, dict):
                record.market_data_date = event.content.get("market_data_date")
                if event.content.get("status") == "pending_provider_settlement":
                    record.status = "market_data_pending"
                    record.decision_status = "market_data_pending"
                elif event.content.get("status") == "unavailable_after_bounded_wait":
                    record.status = "market_data_unavailable"
                    record.decision_status = "unavailable"
            if event.type == "run_completed" and isinstance(event.content, dict):
                record.market_data_date = event.content.get(
                    "market_data_date", record.market_data_date
                )
                record.report_path = event.content.get("report_path")
                record.decision_status = event.content.get(
                    "decision_status", "unavailable"
                )
                if record.decision_status in {"review_required", "unavailable"}:
                    record.status = record.decision_status
            if event.type in {"run_completed", "error"} and isinstance(event.content, dict):
                record.data_status = event.content.get("data_status", record.data_status)
                record.vendor_summary = event.content.get(
                    "vendor_summary", record.vendor_summary
                )
            if event.type == "error" and record.status != "cancelled":
                record.status = runtime_error_status(
                    event.content.get("error_type")
                    if isinstance(event.content, dict)
                    else None
                )
                if isinstance(event.content, dict):
                    record.error = event.content.get("error")

            # Runtime events are already persisted before the Web bridge sees
            # them. Tests and Web-local events still use the default path.
            if persist:
                history_store.add_event(run_id, event)

            # Wake every SSE subscriber; each replays from its own list cursor.
            self._event_condition.notify_all()

    def mark_finished(self, run_id: str, status: RunStatus) -> None:
        with self._lock:
            record = self._runs[run_id]
            if record.status != "failed":
                record.status = status
            record.finished_at = _now()

            history_store.mark_finished(run_id, record.status, finished_at=record.finished_at)

            self._event_condition.notify_all()

    def wait_for_events(
        self, run_id: str, after_index: int, timeout: float
    ) -> bool:
        """Wait until replay has new events or the run reaches a terminal state.

        A condition over the append-only in-memory event list is broadcast-safe:
        multiple SSE clients no longer compete for a single queue item.
        """
        terminal = {
            "completed", "review_required", "unavailable", "failed", "cancelled",
            "market_data_pending", "market_data_unavailable",
            "outcome_settlement_pending", "outcome_settlement_unavailable",
        }
        with self._event_condition:
            return self._event_condition.wait_for(
                lambda: (
                    run_id not in self._runs
                    or len(self._runs[run_id].events) > after_index
                    or self._runs[run_id].status in terminal
                ),
                timeout=timeout,
            )

    def request_cancel(self, run_id: str) -> bool:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                # Try to load from DB (may be a historical run)
                record = self.get(run_id)
            if record is None:
                return False
            if record.status in (
                "completed", "review_required", "unavailable", "failed", "cancelled",
                "market_data_pending", "market_data_unavailable",
                "outcome_settlement_pending", "outcome_settlement_unavailable",
            ):
                return True
            record.cancel_requested = True
            record.status = "cancelled"

            history_store.request_cancel(run_id)
            self._event_condition.notify_all()
            return True

    def delete(self, run_id: str) -> bool:
        with self._lock:
            self._runs.pop(run_id, None)
            return history_store.delete_run(run_id)

    def clear_all(self) -> None:
        with self._lock:
            self._runs.clear()
            history_store.clear_all_runs()



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
