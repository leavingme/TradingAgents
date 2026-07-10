"""Minimal FastAPI backend for TradingAgents WebUI."""

from __future__ import annotations

import asyncio
import json
import os
import queue
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
from tradingagents.llm_clients.openai_client import OPENAI_COMPATIBLE_PROVIDERS
from tradingagents.dataflows.vendor_verification import vendor_verification_store

from .analyst_prompts import analyst_prompt_payload
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
        "data_vendors": DEFAULT_CONFIG.get("data_vendors", {}),
    }


@app.get("/api/config/env-status")
async def get_env_status():
    providers = {}
    for provider, env_var in sorted(PROVIDER_API_KEY_ENV.items()):
        spec = OPENAI_COMPATIBLE_PROVIDERS.get(provider)
        required = env_var is not None and not (spec is not None and spec.key_optional)
        providers[provider] = {
            "env_var": env_var,
            "configured": bool(env_var and os.environ.get(env_var)),
            "required": required,
        }

    # Add data vendors status
    data_vendors = {}
    
    # 1. FRED
    data_vendors["fred"] = {
        "env_var": "FRED_API_KEY",
        "configured": bool(os.environ.get("FRED_API_KEY")),
        "required": True,
    }
    # 2. Alpha Vantage
    data_vendors["alpha_vantage"] = {
        "env_var": "ALPHA_VANTAGE_API_KEY",
        "configured": bool(os.environ.get("ALPHA_VANTAGE_API_KEY")),
        "required": True,
    }
    # 3. Longbridge MCP (presence of token file)
    from tradingagents.dataflows.longbridge_mcp import TOKEN_PATH
    data_vendors["longbridge_mcp"] = {
        "env_var": ".longbridge_mcp_token.json",
        "configured": TOKEN_PATH.exists(),
        "required": True,
    }
    # 4. Longbridge CLI (presence of CLI executable)
    import shutil
    data_vendors["longbridge"] = {
        "env_var": "longbridge CLI in PATH",
        "configured": shutil.which("longbridge") is not None,
        "required": True,
    }
    # 5. Polymarket, DuckDuckGo, and Westock do not require credentials
    for v in ["polymarket", "duckduckgo", "westock"]:
        data_vendors[v] = {
            "env_var": None,
            "configured": True,
            "required": False,
        }

    return {
        "providers": providers,
        "data_vendors": data_vendors,
        "vendor_verifications": vendor_verification_store.list_latest(),
    }


@app.post("/api/config/data-vendors/{category}/{vendor}/verify")
async def verify_data_vendor(category: str, vendor: str):
    from tradingagents.dataflows.interface import verify_vendor

    try:
        result = await asyncio.to_thread(verify_vendor, vendor, category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=500, detail="verification result could not be persisted")
    return result


@app.get("/api/config/analyst-prompts")
async def get_analyst_prompts():
    return analyst_prompt_payload()


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


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    if not store.delete(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    return {"status": "deleted"}


@app.delete("/api/runs")
async def clear_runs():
    store.clear_all()
    return {"status": "cleared"}


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
