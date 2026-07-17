"""Background execution bridge from Web API records to runtime events."""

from __future__ import annotations

import threading

from tradingagents.runtime import AnalysisEvent, AnalysisRequest, run_analysis_stream
from tradingagents.runtime.stats_handler import StatsCallbackHandler

from .models import RunCreateRequest
from .task_store import TaskStore


def to_analysis_request(
    run_id: str,
    request: RunCreateRequest,
    callbacks: tuple[object, ...] = (),
) -> AnalysisRequest:
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
        google_thinking_level=request.google_thinking_level,
        openai_reasoning_effort=request.openai_reasoning_effort,
        anthropic_effort=request.anthropic_effort,
        run_id=run_id,
        config_overrides=request.config_overrides,
        callbacks=callbacks,
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
    stats_handler = StatsCallbackHandler()
    try:
        analysis_request = to_analysis_request(run_id, request, callbacks=(stats_handler,))
        for event in run_analysis_stream(analysis_request):
            record = task_store.get(run_id)
            if record is not None and record.cancel_requested:
                final_status = "cancelled"
                task_store.add_event(
                    run_id,
                    AnalysisEvent(
                        type="run_cancelled",
                        run_id=run_id,
                        content={"message": "run cancelled"},
                    ),
                )
                break

            task_store.add_event(run_id, event, persist=False)
            if event.type == "error":
                final_status = "failed"
                break
            if (
                event.type == "market_data_status"
                and isinstance(event.content, dict)
                and event.content.get("status") == "pending_provider_settlement"
            ):
                final_status = "market_data_pending"
            if (
                event.type == "run_completed"
                and isinstance(event.content, dict)
                and event.content.get("decision_status") in {"review_required", "unavailable"}
            ):
                final_status = event.content["decision_status"]
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
