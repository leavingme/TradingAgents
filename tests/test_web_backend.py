import asyncio
import httpx
import pytest
from fastapi import HTTPException

from tradingagents.runtime import AnalysisEvent


def test_create_run_and_get_status(monkeypatch):
    from web.backend import main

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)
        task_store.add_event(
            run_id,
            AnalysisEvent(type="run_started", run_id=run_id, content={"ticker": request.ticker}),
        )
        task_store.add_event(
            run_id,
            AnalysisEvent(
                type="market_data_status",
                run_id=run_id,
                content={"status": "verified", "market_data_date": "2026-07-03"},
            ),
        )
        task_store.add_event(
            run_id,
            AnalysisEvent(
                type="run_completed",
                run_id=run_id,
                content={"decision": "Hold", "report_path": "/tmp/report.md"},
            ),
        )
        task_store.mark_finished(run_id, "completed")

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(
                ticker="NVDA",
                analysis_date="2026-07-05",
                selected_analysts=["market"],
            )
        )
        status = await main.get_run(created["run_id"])
        return created, status

    created, status = asyncio.run(exercise())

    assert created["ticker"] == "NVDA"
    assert created["status"] == "completed"
    assert created["report_path"] == "/tmp/report.md"
    assert status["market_data_date"] == "2026-07-03"
    assert status["event_count"] == 3


def test_evaluation_api_requires_complete_distinct_architecture_selectors():
    from web.backend import main

    with pytest.raises(HTTPException) as missing_arm:
        asyncio.run(main.get_decision_evaluations(baseline="baseline"))
    assert missing_arm.value.status_code == 422

    with pytest.raises(HTTPException) as same_arm:
        asyncio.run(main.get_decision_evaluations(
            baseline="same",
            challenger="same",
        ))
    assert same_arm.value.status_code == 422

    with pytest.raises(HTTPException) as missing_fingerprint:
        asyncio.run(main.get_decision_evaluations(
            baseline="baseline",
            challenger="challenger",
            baseline_fingerprint="baseline-fp",
        ))
    assert missing_fingerprint.value.status_code == 422

    with pytest.raises(HTTPException) as fingerprints_without_arms:
        asyncio.run(main.get_decision_evaluations(
            baseline_fingerprint="baseline-fp",
            challenger_fingerprint="challenger-fp",
        ))
    assert fingerprints_without_arms.value.status_code == 422

    with pytest.raises(HTTPException) as whitespace_selector:
        asyncio.run(main.get_decision_evaluations(
            baseline=" baseline",
            challenger="challenger",
        ))
    assert whitespace_selector.value.status_code == 422


def test_run_create_request_uses_webui_defaults():
    from web.backend.models import RunCreateRequest
    from web.backend.runner_worker import to_analysis_request

    request = RunCreateRequest(ticker="NVDA", analysis_date="2026-07-05")
    analysis_request = to_analysis_request("run-defaults", request)

    assert analysis_request.llm_provider == "minimax-cn"
    assert analysis_request.quick_think_llm == "MiniMax-M3"
    assert analysis_request.deep_think_llm == "MiniMax-M3"
    assert analysis_request.output_language == "Chinese"


def test_get_config_defaults_matches_webui_defaults():
    from web.backend import main

    defaults = asyncio.run(main.get_config_defaults())

    assert defaults["llm_provider"] == "minimax-cn"
    assert defaults["quick_think_llm"] == "MiniMax-M3"
    assert defaults["deep_think_llm"] == "MiniMax-M3"
    assert defaults["output_language"] == "Chinese"
    assert defaults["research_depth"] == 1


def test_get_analyst_prompts_exposes_prompt_catalog():
    from web.backend import main
    from tradingagents.agents.analysts.prompts import (
        TOOL_CALLING_COLLABORATION_PROMPT,
        build_market_analyst_system_message,
        render_full_prompt,
    )

    payload = asyncio.run(main.get_analyst_prompts())

    keys = {item["key"] for item in payload["analysts"]}
    assert keys == {"market", "social", "news", "fundamentals"}
    market = next(item for item in payload["analysts"] if item["key"] == "market")
    assert "get_verified_market_snapshot" in market["tools"]
    assert market["prompt"] == render_full_prompt(
        TOOL_CALLING_COLLABORATION_PROMPT,
        build_market_analyst_system_message(),
        ["get_indicators", "get_verified_market_snapshot"],
    )


def test_get_env_status_reports_provider_key_presence(monkeypatch):
    from web.backend import main
    from tradingagents.dataflows import longbridge_mcp

    monkeypatch.setenv("MINIMAX_CN_API_KEY", "test-key")
    monkeypatch.setattr(
        longbridge_mcp,
        "_load_token",
        lambda: {
            "access_token": "sentinel-secret",
            "expiry": "2000-01-01T00:00:00+00:00",
        },
    )
    status = asyncio.run(main.get_env_status())

    assert status["providers"]["minimax-cn"]["env_var"] == "MINIMAX_CN_API_KEY"
    assert status["providers"]["minimax-cn"]["configured"] is True
    assert status["providers"]["ollama"]["required"] is False
    assert status["providers"]["openai_compatible"]["required"] is False
    assert status["data_vendors"]["longbridge_mcp"] == {
        "env_var": ".longbridge_mcp_token.json",
        "configured": False,
        "required": True,
        "credential_status": "expired",
        "expires_at": "2000-01-01T00:00:00+00:00",
    }
    assert "sentinel-secret" not in str(status)


def test_run_create_request_passes_webui_config():
    from web.backend.models import RunCreateRequest
    from web.backend.runner_worker import to_analysis_request

    request = RunCreateRequest(
        ticker="NVDA",
        analysis_date="2026-07-05",
        llm_provider="openai",
        quick_think_llm="gpt-5.4-mini",
        deep_think_llm="gpt-5.5",
        research_depth=3,
        backend_url="https://api.openai.com/v1",
        output_language="English",
        google_thinking_level="high",
        openai_reasoning_effort="medium",
        anthropic_effort="low",
    )
    analysis_request = to_analysis_request("run-config", request)

    assert analysis_request.llm_provider == "openai"
    assert analysis_request.quick_think_llm == "gpt-5.4-mini"
    assert analysis_request.deep_think_llm == "gpt-5.5"
    assert analysis_request.research_depth == 3
    assert analysis_request.backend_url == "https://api.openai.com/v1"
    assert analysis_request.output_language == "English"
    assert analysis_request.google_thinking_level == "high"
    assert analysis_request.openai_reasoning_effort == "medium"
    assert analysis_request.anthropic_effort == "low"


def test_run_request_rejects_arbitrary_backend_and_filesystem_paths():
    from pydantic import ValidationError
    from web.backend.models import RunCreateRequest

    with pytest.raises(ValidationError, match="server allowlist"):
        RunCreateRequest(
            ticker="NVDA", analysis_date="2026-07-05",
            backend_url="https://attacker.example/v1",
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        RunCreateRequest(
            ticker="NVDA", analysis_date="2026-07-05",
            report_dir="/tmp/exfiltrate",
        )


def test_run_request_rejects_hidden_config_overrides():
    from pydantic import ValidationError
    from web.backend.models import RunCreateRequest

    with pytest.raises(ValidationError, match="non-Web settings"):
        RunCreateRequest(
            ticker="NVDA", analysis_date="2026-07-05",
            config_overrides={"trade_risk_policy": {"max_position_pct": 100}},
        )


def test_mutating_api_requires_bearer_when_server_token_is_configured(monkeypatch):
    from web.backend import main

    monkeypatch.setenv("TRADINGAGENTS_WEB_AUTH_TOKEN", "web-secret")
    monkeypatch.setattr(main, "start_background_run", lambda *args: None)
    main._RATE_EVENTS.clear()
    payload = {"ticker": "NVDA", "analysis_date": "2026-07-05"}

    async def exercise():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            unauthorized = await client.post("/api/runs", json=payload)
            authorized = await client.post(
                "/api/runs",
                json=payload,
                headers={"Authorization": "Bearer web-secret"},
            )
        return unauthorized, authorized

    unauthorized, response = asyncio.run(exercise())
    assert unauthorized.status_code == 401
    assert response.status_code == 200
    main.store.delete(response.json()["run_id"])


def test_run_create_request_preserves_runtime_callbacks():
    from web.backend.models import RunCreateRequest
    from web.backend.runner_worker import to_analysis_request

    callback = object()
    request = RunCreateRequest(ticker="NVDA", analysis_date="2026-07-05")
    analysis_request = to_analysis_request("run-callbacks", request, callbacks=(callback,))

    assert analysis_request.callbacks == (callback,)


def test_stream_run_events_replays_stored_events(monkeypatch):
    from web.backend import main

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)
        task_store.add_event(
            run_id,
            AnalysisEvent(
                type="vendor_attempt",
                run_id=run_id,
                content={
                    "call_id": "call-news", "attempt": 1,
                    "category": "news_data", "method": "get_news",
                    "vendor": "primary", "status": "rate_limited",
                    "selected": False, "error_type": "VendorRateLimitError",
                    "error_detail": "HTTP 429",
                },
            ),
        )
        task_store.add_event(
            run_id,
            AnalysisEvent(type="message", run_id=run_id, content={"text": "hello"}),
        )
        task_store.mark_finished(run_id, "completed")

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(ticker="MSFT", analysis_date="2026-07-05")
        )
        response = await main.stream_run_events(created["run_id"])
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return "".join(chunks)

    body = asyncio.run(exercise())

    assert "event: message" in body
    assert "event: vendor_attempt" in body
    assert '\"call_id\": \"call-news\"' in body
    assert '\"error_detail\": \"HTTP 429\"' in body
    assert '"text": "hello"' in body


def test_stream_terminal_event_uses_current_vendor_summary(monkeypatch):
    from web.backend import main

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)
        task_store.add_event(run_id, AnalysisEvent(
            type="run_completed",
            run_id=run_id,
            content={
                "decision": "Hold",
                "decision_status": "validated",
                "data_status": "degraded",
                "vendor_summary": {
                    "data_status": "degraded",
                    "unavailable_domains": ["prediction_markets"],
                },
            },
        ))
        record = task_store.get(run_id)
        record.vendor_summary = {
            "data_status": "degraded",
            "partially_available_domains": ["prediction_markets"],
            "unavailable_domains": [],
            "trajectories": [{
                "symbol": "NVDA Nvidia earnings",
                "status": "unavailable",
                "attempts": [{
                    "vendor": "polymarket",
                    "status": "invalid",
                    "error_detail": "expired market",
                }],
            }],
        }
        task_store.mark_finished(run_id, "completed")

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(ticker="NVDA", analysis_date="2026-07-05")
        )
        response = await main.stream_run_events(created["run_id"])
        chunks = [chunk async for chunk in response.body_iterator]
        return "".join(chunks)

    body = asyncio.run(exercise())

    assert '"partially_available_domains": ["prediction_markets"]' in body
    assert '"vendor": "polymarket"' in body
    assert '"error_detail": "expired market"' in body


def test_stream_run_events_does_not_repeat_replayed_live_event(monkeypatch):
    from web.backend import main

    main._RATE_EVENTS.clear()

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)
        task_store.add_event(
            run_id,
            AnalysisEvent(type="message", run_id=run_id, content={"text": "first"}),
        )

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(ticker="NVDA", analysis_date="2026-07-05")
        )
        run_id = created["run_id"]
        response = await main.stream_run_events(run_id)
        iterator = response.body_iterator
        first = await anext(iterator)
        main.store.add_event(
            run_id,
            AnalysisEvent(type="message", run_id=run_id, content={"text": "second"}),
        )
        main.store.mark_finished(run_id, "completed")
        second = await anext(iterator)
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)
        return run_id, first, second

    run_id, first, second = asyncio.run(exercise())
    assert '"text": "first"' in first
    assert '"text": "second"' in second
    assert '"text": "first"' not in second
    main.store.delete(run_id)
    main._RATE_EVENTS.clear()


def test_stream_run_events_keeps_heartbeat_when_idle(monkeypatch):
    from web.backend import main

    main._RATE_EVENTS.clear()

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)

    async def immediate_timeout(func, *args, **kwargs):
        return False

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)
    monkeypatch.setattr(main.asyncio, "to_thread", immediate_timeout)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(ticker="NVDA", analysis_date="2026-07-05")
        )
        response = await main.stream_run_events(created["run_id"])
        heartbeat = await anext(response.body_iterator)
        await response.body_iterator.aclose()
        return created["run_id"], heartbeat

    run_id, heartbeat = asyncio.run(exercise())
    assert heartbeat == ": heartbeat\n\n"
    main.store.delete(run_id)
    main._RATE_EVENTS.clear()


def test_runner_bridge_does_not_persist_runtime_events_twice(monkeypatch):
    from web.backend import runner_worker

    events = [
        AnalysisEvent(type="run_started", run_id="run-once", content={}),
        AnalysisEvent(
            type="run_completed",
            run_id="run-once",
            content={"decision_status": "validated"},
        ),
    ]

    class FakeStore:
        def __init__(self):
            self.persist_flags = []
            self.status = None

        def mark_started(self, run_id):
            pass

        def get(self, run_id):
            return type("Record", (), {"cancel_requested": False})()

        def add_event(self, run_id, event, *, persist=True):
            self.persist_flags.append(persist)

        def mark_finished(self, run_id, status):
            self.status = status

    store = FakeStore()
    monkeypatch.setattr(runner_worker, "run_analysis_stream", lambda request: iter(events))
    runner_worker._run(
        "run-once",
        runner_worker.RunCreateRequest(ticker="NVDA", analysis_date="2026-07-05"),
        store,
    )

    assert store.persist_flags == [False, False]
    assert store.status == "completed"


def test_get_run_report_returns_markdown(monkeypatch, tmp_path):
    from web.backend import main

    monkeypatch.setitem(main.DEFAULT_CONFIG, "results_dir", str(tmp_path))

    report_path = tmp_path / "complete_report.md"
    report_path.write_text("# Report\n\nHold", encoding="utf-8")

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)
        task_store.add_event(
            run_id,
            AnalysisEvent(
                type="run_completed",
                run_id=run_id,
                content={"decision": "Hold", "report_path": str(report_path)},
            ),
        )
        task_store.mark_finished(run_id, "completed")

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(ticker="AAPL", analysis_date="2026-07-05")
        )
        return await main.get_run_report(created["run_id"])

    response = asyncio.run(exercise())

    assert response.media_type == "text/markdown"
    assert response.body.decode("utf-8") == "# Report\n\nHold"


def test_get_run_vendor_calls_returns_run_scoped_ledger(monkeypatch):
    from web.backend import main
    import tradingagents.runtime as runtime

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)
        task_store.mark_finished(run_id, "completed")

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)
    expected = [{"call_id": "call-1", "attempt": 1, "vendor": "westock"}]
    monkeypatch.setattr(runtime.history_store, "get_vendor_calls", lambda run_id: expected)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(ticker="NVDA", analysis_date="2026-07-10")
        )
        return await main.get_run_vendor_calls(created["run_id"])

    assert asyncio.run(exercise()) == expected


def test_run_response_exposes_persisted_vendor_health(monkeypatch):
    from web.backend import main

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)
        task_store.add_event(run_id, AnalysisEvent(
            type="run_completed",
            run_id=run_id,
            content={
                "decision": "Hold", "decision_status": "validated",
                "data_status": "degraded",
                "vendor_summary": {
                    "data_status": "degraded",
                    "fallback_domains": ["news_data"],
                    "unavailable_domains": [],
                },
            },
        ))
        task_store.mark_finished(run_id, "completed")

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(ticker="NVDA", analysis_date="2026-07-10")
        )
        return await main.get_run(created["run_id"])

    response = asyncio.run(exercise())
    assert response["status"] == "completed"
    assert response["decision_status"] == "validated"
    assert response["data_status"] == "degraded"
    assert response["vendor_summary"]["fallback_domains"] == ["news_data"]


def test_web_index_serves_frontend_file():
    from web.backend import main

    response = asyncio.run(main.web_index())

    assert str(response.path).endswith("web/frontend/index.html")


def test_failed_run_status_is_recorded(monkeypatch):
    from web.backend import main

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)
        task_store.add_event(
            run_id,
            AnalysisEvent(
                type="error",
                run_id=run_id,
                content={"error": "boom", "error_type": "RuntimeError"},
            ),
        )
        task_store.mark_finished(run_id, "failed")

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(ticker="TSLA", analysis_date="2026-07-05")
        )
        return await main.get_run(created["run_id"])

    status = asyncio.run(exercise())

    assert status["status"] == "failed"
    assert status["error"] == "boom"


def test_cancel_run_marks_record_cancelled(monkeypatch):
    from web.backend import main

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(ticker="AMD", analysis_date="2026-07-05")
        )
        return await main.cancel_run(created["run_id"])

    cancelled = asyncio.run(exercise())

    assert cancelled["status"] == "cancelled"


def test_list_runs_returns_created_records(monkeypatch):
    from web.backend import main

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)
        task_store.mark_finished(run_id, "completed")

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        first = await main.create_run(
            main.RunCreateRequest(ticker="IBM", analysis_date="2026-07-05")
        )
        second = await main.create_run(
            main.RunCreateRequest(ticker="ORCL", analysis_date="2026-07-05")
        )
        runs = await main.list_runs()
        return first, second, runs

    first, second, runs = asyncio.run(exercise())
    ids = [run["run_id"] for run in runs]

    assert second["run_id"] in ids
    assert first["run_id"] in ids
    assert ids.index(second["run_id"]) < ids.index(first["run_id"])


def test_store_trims_full_final_state_before_persisting(tmp_path):
    from web.backend.models import RunCreateRequest
    from web.backend.task_store import TaskStore

    store = TaskStore(tmp_path / "runs.db")
    store.create("run-json-safe", RunCreateRequest(ticker="NVDA", analysis_date="2026-07-05"))
    store.mark_started("run-json-safe")
    store.add_event(
        "run-json-safe",
        AnalysisEvent(
            type="run_completed",
            run_id="run-json-safe",
            content={
                "decision": "Hold",
                "report_path": str(tmp_path / "report.md"),
                "final_state": {"non_json": object()},
            },
        ),
    )
    store.mark_finished("run-json-safe", "completed")

    record = store.get("run-json-safe")
    assert record is not None
    assert record.status == "completed"
    assert isinstance(record.events[-1].content, dict)
    assert record.events[-1].content == {
        "decision": "Hold",
        "report_path": str(tmp_path / "report.md"),
    }


def test_build_runtime_config_merges_nested_overrides():
    from web.backend.models import RunCreateRequest
    from web.backend.runner_worker import to_analysis_request
    from tradingagents.runtime.config_builder import build_runtime_config

    request = RunCreateRequest(
        ticker="NVDA",
        analysis_date="2026-07-05",
        config_overrides={
            "data_vendors": {
                "core_stock_apis": "westock",
            }
        }
    )
    analysis_request = to_analysis_request("run-test-nested", request)
    config = build_runtime_config(analysis_request)

    assert config["data_vendors"]["core_stock_apis"] == "westock"
    # Ensure other default values in data_vendors are NOT lost
    assert config["data_vendors"]["news_data"] == "longbridge_mcp, longbridge, westock, duckduckgo, alpha_vantage"


def test_manual_vendor_verification_endpoint(monkeypatch):
    from tradingagents.dataflows import interface
    from web.backend import main

    expected = {
        "vendor": "westock",
        "category": "news_data",
        "method": "get_news",
        "status": "available",
        "source": "manual",
        "detail": None,
        "latency_ms": 25,
        "verified_at": "2026-07-10T01:02:03+00:00",
    }
    monkeypatch.setattr(interface, "verify_vendor", lambda vendor, category: expected)

    async def run_inline(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", run_inline)

    result = asyncio.run(main.verify_data_vendor("news_data", "westock"))

    assert result == expected


def test_evaluation_endpoint_returns_rows_and_rollups():
    from tradingagents.runtime import history_store
    from web.backend import main

    history_store.create_run(
        "evaluated-run",
        "NVDA",
        "2026-07-01",
        "stock",
        ["market"],
        "minimax-cn",
        1,
        architecture_version="baseline",
    )
    history_store.mark_started(
        "evaluated-run", started_at="2026-07-01T20:00:00+00:00"
    )
    history_store.add_event("evaluated-run", AnalysisEvent(
        type="stats",
        run_id="evaluated-run",
        content={"llm_calls": 9, "tool_calls": 18, "tokens_in": 900, "tokens_out": 180},
    ))
    history_store.add_event("evaluated-run", AnalysisEvent(
        type="run_completed",
        run_id="evaluated-run",
        timestamp="2026-07-01T21:00:00+00:00",
        content={
            "decision": "Rating: Buy",
            "decision_status": "validated",
            "decision_as_of": "2026-07-01T21:00:00+00:00",
        },
    ))
    history_store.mark_finished(
        "evaluated-run", "completed", finished_at="2026-07-01T20:02:00+00:00"
    )
    history_store.add_decision_evaluation({
        "run_id": "evaluated-run",
        "horizon_sessions": 5,
        "ticker": "NVDA",
        "analysis_date": "2026-07-01",
        "rating": "Buy",
        "benchmark": "SPY",
        "entry_date": "2026-07-02",
        "exit_date": "2026-07-09",
        "stock_entry_close": 100.0,
        "stock_exit_close": 104.0,
        "benchmark_entry_close": 500.0,
        "benchmark_exit_close": 505.0,
        "stock_entry_source_id": "ohlcv:test:stock-entry:2026-07-02",
        "stock_exit_source_id": "ohlcv:test:stock-exit:2026-07-09",
        "benchmark_entry_source_id": "ohlcv:test:bench-entry:2026-07-02",
        "benchmark_exit_source_id": "ohlcv:test:bench-exit:2026-07-09",
        "decision_as_of": "2026-07-01T21:00:00+00:00",
        "decision_timezone": "America/New_York",
        "entry_cutoff_date": "2026-07-01",
        "raw_return": 0.04,
        "benchmark_return": 0.01,
        "alpha_return": 0.03,
        "exposure": 1.0,
        "directional_hit": True,
        "score": 0.03,
        "architecture_version": "baseline",
    })
    history_store.create_run(
        "pending-evaluation-run",
        "NVDA",
        "2026-07-10",
        "stock",
        ["market"],
        "minimax-cn",
        1,
        architecture_version="baseline",
        architecture_fingerprint="pending-fingerprint",
    )
    history_store.add_event("pending-evaluation-run", AnalysisEvent(
        type="run_completed",
        run_id="pending-evaluation-run",
        timestamp="2026-07-10T21:00:00+00:00",
        content={
            "decision": "Rating: Hold",
            "decision_status": "validated",
            "decision_as_of": "2026-07-10T21:00:00+00:00",
        },
    ))

    response = asyncio.run(main.get_decision_evaluations(ticker="nvda", limit=50))
    assert len(response["evaluations"]) == 1
    assert response["pending_evaluation_count"] == 1
    assert response["pending_evaluations"] == [{
        "run_id": "pending-evaluation-run",
        "ticker": "NVDA",
        "analysis_date": "2026-07-10",
        "market_data_date": None,
        "decision_as_of": "2026-07-10T21:00:00+00:00",
        "architecture_version": "baseline",
        "architecture_fingerprint": "pending-fingerprint",
        "started_at": None,
        "finished_at": None,
        "horizon_sessions": 5,
        "status": "awaiting_fixed_horizon_outcome",
    }]
    assert response["evaluations"][0]["runtime_seconds"] == 120.0
    assert response["evaluations"][0]["tokens_in"] == 900
    assert response["rollups"] == [{
        "architecture_version": "baseline",
        "architecture_fingerprint": "legacy-unspecified",
        "measurement_version": "post-decision-day-close-v1",
        "scoring_version": "alpha-exposure-v1",
        "hold_band": 0.02,
        "horizon_sessions": 5,
        "sample_count": 1,
        "directional_hit_rate": 1.0,
        "mean_raw_return": 0.04,
        "mean_alpha_return": 0.03,
        "mean_score": 0.03,
        "analysis_data_status_counts": {"not_observed": 1},
        "analysis_evidence_complete_count": 0,
        "architecture_input_complete_count": 0,
        "outcome_assessment": {
            "schema": "tradingagents/architecture-outcome-assessment/v2",
            "status": "insufficient_samples",
            "minimum_samples": 20,
            "score_sample_count": 1,
            "temporal_sample_count": 1,
            "missing_temporal_windows": 0,
            "mean_score": 0.03,
            "median_score": 0.03,
            "score_standard_deviation": None,
            "negative_score_rate": 0.0,
            "worst_score": 0.03,
            "mean_negative_score": None,
            "median_alpha_return": 0.03,
            "median_raw_return": 0.04,
            "lower_95_mean_score": None,
            "upper_95_mean_score": None,
            "critical_value": None,
            "critical_effective_sample_count": 1,
            "standard_error": None,
            "iid_standard_error": None,
            "overlap_adjusted_standard_error": None,
            "overlap_effective_sample_size": 1.0,
            "autocorrelation_lags": 0,
            "overlap_pairs_used": 0,
            "standard_error_method": "max(iid, overlap-aware-newey-west)",
            "rating_breakdown": {
                "buy": {
                    "sample_count": 1,
                    "directional_hit_rate": 1.0,
                    "mean_alpha_return": 0.03,
                    "mean_score": 0.03,
                }
            },
            "rolling_monitoring": {
                "schema": "tradingagents/rolling-outcome-monitoring/v1",
                "interpretation": (
                    "Descriptive recent-versus-previous monitoring only. "
                    "Sequential windows can overlap in return exposure and remain "
                    "regime-confounded."
                ),
                "automatic_architecture_mutation_allowed": False,
                "causal_claim_allowed": False,
                "ordering": "ticker_then_analysis_date",
                "window_sizes": [5, 10, 20],
                "invalid_rows_excluded": 0,
                "tickers": {
                    "NVDA": {
                        "distinct_analysis_date_count": 1,
                        "ambiguous_analysis_date_count": 0,
                        "ambiguous_rows_excluded": 0,
                        "windows": {
                            str(size): {
                                "status": "insufficient_history",
                                "required_samples": 2 * size,
                                "current": {
                                    "sample_count": 1,
                                    "from_analysis_date": "2026-07-01",
                                    "through_analysis_date": "2026-07-01",
                                    "mean_score": 0.03,
                                    "median_score": 0.03,
                                    "mean_alpha_return": 0.03,
                                    "directional_hit_rate": 1.0,
                                    "negative_score_rate": 0.0,
                                },
                                "previous": {
                                    "sample_count": 0,
                                    "from_analysis_date": None,
                                    "through_analysis_date": None,
                                    "mean_score": None,
                                    "median_score": None,
                                    "mean_alpha_return": None,
                                    "directional_hit_rate": None,
                                    "negative_score_rate": None,
                                },
                                "current_minus_previous": None,
                            }
                            for size in (5, 10, 20)
                        },
                    }
                },
            },
        },
        "optimization_assessment": {
            "schema": (
                "tradingagents/"
                "single-architecture-optimization-assessment/v1"
            ),
            "automatic_mutation_allowed": False,
            "paired_shadow_authorization_required": True,
            "readiness_status": "insufficient_outcome_samples",
            "recommended_action": "continue_sample_collection",
            "controlled_experiment_ready": False,
            "evidence": {
                "sample_count": 1,
                "minimum_samples": 20,
                "outcome_status": "insufficient_samples",
                "analysis_evidence_complete_count": 0,
                "architecture_input_complete_count": 0,
                "input_audit_complete": False,
                "persistent_underperformance_supported": False,
            },
            "recent_deterioration_signals": [],
            "cost_hotspots": [],
            "weakest_rating": {
                "rating": "buy",
                "sample_count": 1,
                "mean_score": 0.03,
            },
        },
        "runtime_seconds_sample_count": 1,
        "mean_runtime_seconds": 120.0,
        "llm_calls_sample_count": 1,
        "mean_llm_calls": 9.0,
        "tool_calls_sample_count": 1,
        "mean_tool_calls": 18.0,
        "tokens_in_sample_count": 1,
        "mean_tokens_in": 900.0,
        "tokens_out_sample_count": 1,
        "mean_tokens_out": 180.0,
    }]

    comparison = asyncio.run(main.get_decision_evaluations(
        ticker="nvda",
        baseline="baseline",
        challenger="candidate",
    ))
    assert comparison["comparison"]["status"] == "insufficient_data"
    assert comparison["comparison"]["sample_progress"] == {
        "baseline": 1,
        "challenger": 0,
        "minimum_required_each": 20,
        "sufficient": False,
    }
    assert comparison["comparison"]["missing_architectures"] == ["candidate"]

    with pytest.raises(main.HTTPException) as exc_info:
        asyncio.run(main.get_decision_evaluations(
            ticker="nvda",
            baseline="baseline",
        ))
    assert exc_info.value.status_code == 422
