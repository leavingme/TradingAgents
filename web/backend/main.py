"""Minimal FastAPI backend for TradingAgents WebUI."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
from tradingagents.llm_clients.openai_client import OPENAI_COMPATIBLE_PROVIDERS
from tradingagents.dataflows.vendor_verification import vendor_verification_store

from .analyst_prompts import analyst_prompt_payload
from .models import (
    RunCreateRequest,
    RunRecordResponse,
    _normalise_backend_url,
    allowed_backend_urls,
)
from .runner_worker import start_background_run
from .task_store import store
from .web_config_store import web_config_store

app = FastAPI(title="TradingAgents Web API")
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_RATE_LOCK = threading.Lock()
_RATE_EVENTS: dict[str, deque[float]] = defaultdict(deque)


def _bearer_is_valid(request: Request) -> bool:
    expected = os.environ.get("TRADINGAGENTS_WEB_AUTH_TOKEN", "")
    supplied = request.headers.get("authorization", "")
    if not expected or not supplied.startswith("Bearer "):
        return False
    return secrets.compare_digest(supplied[7:], expected)


@app.middleware("http")
async def enforce_api_authentication(request: Request, call_next):
    """Protect all remote APIs and every mutation when a server token is configured."""
    if request.url.path.startswith("/api/"):
        require_all = os.environ.get("TRADINGAGENTS_WEB_REQUIRE_AUTH") == "1"
        token_configured = bool(os.environ.get("TRADINGAGENTS_WEB_AUTH_TOKEN"))
        protected = require_all or (token_configured and request.method in _MUTATING_METHODS)
        if protected and not _bearer_is_valid(request):
            status = 503 if require_all and not token_configured else 401
            return JSONResponse(
                status_code=status,
                content={"detail": "valid Web API bearer token required"},
            )
    return await call_next(request)


def _enforce_rate(bucket: str, *, limit: int, window_seconds: int = 60) -> None:
    now = time.monotonic()
    with _RATE_LOCK:
        events = _RATE_EVENTS[bucket]
        while events and events[0] <= now - window_seconds:
            events.popleft()
        if len(events) >= limit:
            raise HTTPException(status_code=429, detail="request rate limit exceeded")
        events.append(now)


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


@app.get("/api/config/web")
async def get_web_config():
    return web_config_store.load()


@app.put("/api/config/web")
async def update_web_config(payload: dict):
    _enforce_rate("config-mutation", limit=30)
    settings = payload.get("settings") if isinstance(payload, dict) else None
    if isinstance(settings, dict) and settings.get("backend_url"):
        backend_url = _normalise_backend_url(str(settings["backend_url"]))
        if backend_url not in allowed_backend_urls():
            raise HTTPException(
                status_code=400,
                detail="backend_url is not present in the server allowlist",
            )
        settings["backend_url"] = backend_url
    return web_config_store.save(payload)


@app.delete("/api/config/web")
async def reset_web_config():
    _enforce_rate("config-mutation", limit=30)
    return web_config_store.reset()


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
    data_vendors["bird"] = {
        "env_var": "AUTH_TOKEN + CT0 / browser cookies",
        "configured": shutil.which("bird") is not None and bool(
            os.environ.get("AUTH_TOKEN") and os.environ.get("CT0")
        ),
        "required": True,
    }
    data_vendors["reddit"] = {
        "env_var": None,
        "configured": True,
        "required": False,
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

    _enforce_rate("vendor-verification", limit=20)
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
    _enforce_rate(
        "run-create",
        limit=int(os.environ.get("TRADINGAGENTS_WEB_RUN_RATE_LIMIT", "10")),
    )
    max_active = int(os.environ.get("TRADINGAGENTS_WEB_MAX_ACTIVE_RUNS", "2"))
    active = sum(record.status in {"pending", "running"} for record in store.list())
    if active >= max_active:
        raise HTTPException(
            status_code=429,
            detail=f"maximum concurrent analysis runs reached ({max_active})",
        )
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

            if current.status in (
                "completed", "review_required", "unavailable", "failed", "cancelled"
            ):
                break

            ready = await asyncio.to_thread(
                store.wait_for_events, run_id, replay_index, 15
            )
            if not ready:
                yield ": heartbeat\n\n"
                continue

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/runs/{run_id}/vendor-calls")
async def get_run_vendor_calls(run_id: str):
    if store.get(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    from tradingagents.runtime import history_store

    return history_store.get_vendor_calls(run_id)


@app.get("/api/runs/{run_id}/report", response_class=PlainTextResponse)
async def get_run_report(run_id: str):
    record = store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not record.report_path:
        raise HTTPException(status_code=404, detail="report not available")

    report_path = Path(record.report_path)
    allowed_root = Path(DEFAULT_CONFIG["results_dir"]).expanduser().resolve()
    try:
        resolved_report = report_path.expanduser().resolve(strict=True)
        resolved_report.relative_to(allowed_root)
    except (OSError, ValueError):
        raise HTTPException(status_code=403, detail="report path is outside approved root")
    if not resolved_report.is_file():
        raise HTTPException(status_code=404, detail="report file not found")
    return PlainTextResponse(
        resolved_report.read_text(encoding="utf-8"), media_type="text/markdown"
    )


@app.post("/api/runs/{run_id}/cancel", response_model=RunRecordResponse)
async def cancel_run(run_id: str):
    _enforce_rate("run-mutation", limit=60)
    if not store.request_cancel(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    record = store.get(run_id)
    return record.to_response()


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    _enforce_rate("run-mutation", limit=60)
    if not store.delete(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    return {"status": "deleted"}


@app.delete("/api/runs")
async def clear_runs():
    _enforce_rate("run-mutation", limit=60)
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
