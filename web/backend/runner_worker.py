"""Background execution bridge from Web API records to runtime events."""

from __future__ import annotations

import threading

from tradingagents.runtime import AnalysisEvent, AnalysisRequest, run_analysis_stream

from .models import RunCreateRequest
from .task_store import TaskStore


def to_analysis_request(run_id: str, request: RunCreateRequest) -> AnalysisRequest:
    return AnalysisRequest(
        ticker=request.ticker,
        analysis_date=request.analysis_date,
        asset_type=request.asset_type,
        selected_analysts=tuple(request.selected_analysts),
        llm_provider=request.llm_provider,
        quick_think_llm=request.quick_think_llm,
        deep_think_llm=request.deep_think_llm,
        research_depth=request.research_depth,
        backend_url=request.backend_url,
        output_language=request.output_language,
        checkpoint_enabled=request.checkpoint_enabled,
        results_dir=request.results_dir,
        report_dir=request.report_dir,
        run_id=run_id,
        config_overrides=request.config_overrides,
    )


def start_background_run(run_id: str, request: RunCreateRequest, task_store: TaskStore) -> None:
    thread = threading.Thread(
        target=_run,
        args=(run_id, request, task_store),
        name=f"analysis-run-{run_id}",
        daemon=True,
    )
    thread.start()


def _run(run_id: str, request: RunCreateRequest, task_store: TaskStore) -> None:
    task_store.mark_started(run_id)
    final_status = "completed"
    try:
        for event in run_analysis_stream(to_analysis_request(run_id, request)):
            record = task_store.get(run_id)
            if record is not None and record.cancel_requested:
                final_status = "cancelled"
                task_store.add_event(
                    run_id,
                    AnalysisEvent(
                        type="error",
                        run_id=run_id,
                        content={"error": "run cancelled", "error_type": "Cancelled"},
                    ),
                )
                break

            task_store.add_event(run_id, event)
            if event.type == "error":
                final_status = "failed"
                break
    except Exception as exc:
        final_status = "failed"
        task_store.add_event(
            run_id,
            AnalysisEvent(
                type="error",
                run_id=run_id,
                content={"error": str(exc), "error_type": type(exc).__name__},
            ),
        )
    finally:
        task_store.mark_finished(run_id, final_status)
