"""Minimal FastAPI backend for TradingAgents WebUI."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from .models import RunCreateRequest, RunRecordResponse
from .runner_worker import start_background_run
from .task_store import store

app = FastAPI(title="TradingAgents Web API")


@app.post("/api/runs", response_model=RunRecordResponse)
async def create_run(request: RunCreateRequest):
    run_id = request.ticker.strip().upper() + "-" + __import__("uuid").uuid4().hex[:12]
    record = store.create(run_id, request)
    start_background_run(run_id, request, store)
    return record.to_response()


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

            event = await asyncio.to_thread(current.event_queue.get)
            if event is None:
                continue
            # The event is already in current.events; replay loop will emit it.

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/runs/{run_id}/cancel", response_model=RunRecordResponse)
async def cancel_run(run_id: str):
    if not store.request_cancel(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    record = store.get(run_id)
    return record.to_response()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
