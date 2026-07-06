"""Minimal FastAPI backend for TradingAgents WebUI."""

from __future__ import annotations

import asyncio
import json
import queue
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .models import RunCreateRequest, RunRecordResponse
from .runner_worker import start_background_run
from .task_store import store

app = FastAPI(title="TradingAgents Web API")
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


@app.get("/api/config/defaults")
async def get_config_defaults():
    fields = RunCreateRequest.model_fields
    return {
        "llm_provider": fields["llm_provider"].default,
        "quick_think_llm": fields["quick_think_llm"].default,
        "deep_think_llm": fields["deep_think_llm"].default,
        "backend_url": fields["backend_url"].default,
        "output_language": fields["output_language"].default,
        "research_depth": fields["research_depth"].default or 1,
        "google_thinking_level": fields["google_thinking_level"].default,
        "openai_reasoning_effort": fields["openai_reasoning_effort"].default,
        "anthropic_effort": fields["anthropic_effort"].default,
    }


@app.post("/api/runs", response_model=RunRecordResponse)
async def create_run(request: RunCreateRequest):
    run_id = request.ticker.strip().upper() + "-" + __import__("uuid").uuid4().hex[:12]
    record = store.create(run_id, request)
    start_background_run(run_id, request, store)
    return record.to_response()


@app.get("/api/runs", response_model=list[RunRecordResponse])
async def list_runs():
    return [record.to_response() for record in store.list()]


@app.get("/api/runs/{run_id}", response_model=RunRecordResponse)
async def get_run(run_id: str):
    record = store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return record.to_response()


@app.get("/api/runs/{run_id}/events")
async def stream_run_events(run_id: str):
    record = store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")

    async def event_stream():
        replay_index = 0
        while True:
            current = store.get(run_id)
            if current is None:
                yield _sse("error", {"error": "run not found"})
                break

            while replay_index < len(current.events):
                event = current.events[replay_index]
                replay_index += 1
                yield _sse(event.type, event.to_dict())

            if current.status in ("completed", "failed", "cancelled"):
                break

            try:
                event = await asyncio.to_thread(current.event_queue.get, True, 15)
            except queue.Empty:
                yield ": heartbeat\n\n"
                continue
            if event is None:
                break
            replay_index += 1
            yield _sse(event.type, event.to_dict())

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/runs/{run_id}/report", response_class=PlainTextResponse)
async def get_run_report(run_id: str):
    record = store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not record.report_path:
        raise HTTPException(status_code=404, detail="report not available")

    report_path = Path(record.report_path)
    if not report_path.exists() or not report_path.is_file():
        raise HTTPException(status_code=404, detail="report file not found")
    return PlainTextResponse(report_path.read_text(encoding="utf-8"), media_type="text/markdown")


@app.post("/api/runs/{run_id}/cancel", response_model=RunRecordResponse)
async def cancel_run(run_id: str):
    if not store.request_cancel(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    record = store.get(run_id)
    return record.to_response()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
async def web_index():
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="frontend not built")
    return FileResponse(index)
