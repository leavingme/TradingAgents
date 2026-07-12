import asyncio

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
    assert status["event_count"] == 2


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
        ["get_stock_data", "get_indicators", "get_verified_market_snapshot"],
    )


def test_get_env_status_reports_provider_key_presence(monkeypatch):
    from web.backend import main

    monkeypatch.setenv("MINIMAX_CN_API_KEY", "test-key")
    status = asyncio.run(main.get_env_status())

    assert status["providers"]["minimax-cn"]["env_var"] == "MINIMAX_CN_API_KEY"
    assert status["providers"]["minimax-cn"]["configured"] is True
    assert status["providers"]["ollama"]["required"] is False
    assert status["providers"]["openai_compatible"]["required"] is False


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
        backend_url="https://example.invalid/v1",
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
    assert analysis_request.backend_url == "https://example.invalid/v1"
    assert analysis_request.output_language == "English"
    assert analysis_request.google_thinking_level == "high"
    assert analysis_request.openai_reasoning_effort == "medium"
    assert analysis_request.anthropic_effort == "low"


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
    assert '"text": "hello"' in body


def test_get_run_report_returns_markdown(monkeypatch, tmp_path):
    from web.backend import main

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
    assert config["data_vendors"]["news_data"] == "westock, duckduckgo, alpha_vantage"


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

    result = asyncio.run(main.verify_data_vendor("news_data", "westock"))

    assert result == expected
