import json
import sqlite3

import pytest
from pathlib import Path
from tradingagents.runtime import AnalysisRequest, run_analysis_once, history_store, RunHistoryStore
from tradingagents.runtime.events import AnalysisEvent
from tradingagents.runtime.history import analysis_evidence_identity, summarize_vendor_calls
from unittest import mock


def test_pytest_runtime_and_web_share_only_the_per_test_database(
    _isolate_run_storage,
):
    from tradingagents import runtime as runtime_module
    from tradingagents.runtime import history as history_module
    from web.backend import task_store as task_store_module

    db_path = _isolate_run_storage
    assert history_module.history_store is runtime_module.history_store
    assert task_store_module.history_store is runtime_module.history_store
    assert runtime_module.history_store._db_path == db_path
    assert runtime_module.history_store.list_runs() == []

    runtime_module.history_store.create_run(
        run_id="isolation-probe",
        ticker="NVDA",
        analysis_date="2026-07-10",
        asset_type="stock",
        selected_analysts=("market",),
        llm_provider="test",
        research_depth=1,
    )
    assert task_store_module.store.get("isolation-probe") is not None


def test_runtime_db_path_only_uses_unified_environment_variable(monkeypatch, tmp_path: Path):
    from tradingagents.runtime import history as history_module

    unified = tmp_path / "unified.db"
    monkeypatch.setenv("TRADINGAGENTS_DB", str(unified))
    monkeypatch.setenv("TRADINGAGENTS_WEBUI_DB", str(tmp_path / "legacy.db"))
    assert history_module._default_db_path() == unified

    monkeypatch.delenv("TRADINGAGENTS_DB")
    monkeypatch.setattr(history_module.Path, "home", lambda: tmp_path)
    assert history_module._default_db_path() == tmp_path / ".tradingagents" / "runs.db"


def test_history_migrates_legacy_evaluations_to_explicit_scoring_policy(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE decision_evaluations (
                run_id TEXT NOT NULL,
                horizon_sessions INTEGER NOT NULL,
                architecture_fingerprint TEXT NOT NULL DEFAULT 'legacy-unspecified',
                PRIMARY KEY (run_id, horizon_sessions)
            )
        """)

    store = RunHistoryStore(db_path)
    with store._conn() as conn:
        columns = {
            row["name"]: row
            for row in conn.execute("PRAGMA table_info(decision_evaluations)")
        }
    assert columns["scoring_version"]["dflt_value"] == "'alpha-exposure-v1'"
    assert columns["measurement_version"]["dflt_value"] == "'decision-close-v1'"
    assert float(columns["hold_band"]["dflt_value"]) == 0.02
    assert columns["decision_as_of"]["dflt_value"] is None
    assert columns["decision_timezone"]["dflt_value"] is None
    assert columns["entry_cutoff_date"]["dflt_value"] is None
    assert columns["analysis_data_status"]["dflt_value"] == "'not_observed'"
    assert columns["analysis_evidence_fingerprint"]["dflt_value"] is None
    assert int(columns["analysis_evidence_complete"]["dflt_value"]) == 0
    assert columns["architecture_input_schema"]["dflt_value"] is None
    assert columns["architecture_input_fingerprint"]["dflt_value"] is None
    assert int(columns["architecture_input_complete"]["dflt_value"]) == 0
    assert columns["market_data_date"]["dflt_value"] is None


def test_analysis_evidence_identity_ignores_execution_noise_but_binds_results():
    base = {
        "call_id": "call-a",
        "attempt": 1,
        "category": "core_stock_apis",
        "method": "get_stock_data",
        "vendor": "longbridge_mcp",
        "agent": "Market Analyst",
        "symbol": "NVDA",
        "status": "available",
        "selected": True,
        "arguments_json": '{"end":"2026-07-01","symbol":"NVDA"}',
        "latency_ms": 10,
        "result_hash": "result-a",
        "started_at": "2026-07-01T20:00:00+00:00",
        "finished_at": "2026-07-01T20:00:01+00:00",
    }
    noisy_copy = {
        **base,
        "call_id": "unrelated-call-id",
        "arguments_json": '{"symbol":"NVDA","end":"2026-07-01"}',
        "latency_ms": 999,
        "started_at": "2026-07-01T20:05:00+00:00",
        "finished_at": "2026-07-01T20:05:09+00:00",
    }
    first = analysis_evidence_identity([base])
    second = analysis_evidence_identity([noisy_copy])
    changed = analysis_evidence_identity([{**base, "result_hash": "result-b"}])
    assert first["complete"] is True
    assert first["data_status"] == "available"
    assert first["fingerprint"] == second["fingerprint"]
    assert first["fingerprint"] != changed["fingerprint"]
    assert analysis_evidence_identity([])["complete"] is False


def test_history_persists_only_verified_market_dates_on_or_before_request(tmp_path):
    store = RunHistoryStore(tmp_path / "runs.db")
    store.create_run(
        "market-date-run", "NVDA", "2026-07-05", "stock", ["market"],
        "minimax-cn", 1,
    )
    store.update_run_market_data_date("market-date-run", "2026-07-03")
    assert store.get_run("market-date-run")["market_data_date"] == "2026-07-03"

    with pytest.raises(ValueError, match="cannot follow"):
        store.update_run_market_data_date("market-date-run", "2026-07-06")
    with pytest.raises(ValueError, match="must be YYYY-MM-DD"):
        store.update_run_market_data_date(
            "market-date-run", "2026-07-03T16:00:00-04:00"
        )
    with pytest.raises(ValueError, match="run_id does not exist"):
        store.update_run_market_data_date("missing-run", "2026-07-03")

    store.create_run(
        "event-market-date", "NVDA", "2026-07-05", "stock", ["market"],
        "minimax-cn", 1,
    )
    store.add_event(
        "event-market-date",
        AnalysisEvent(
            type="market_data_status",
            run_id="event-market-date",
            content={"status": "verified", "market_data_date": "2026-07-03"},
        ),
    )
    assert store.get_run("event-market-date")["market_data_date"] == "2026-07-03"
    with pytest.raises(ValueError, match="cannot follow"):
        store.add_event(
            "event-market-date",
            AnalysisEvent(
                type="market_data_status",
                run_id="event-market-date",
                content={"status": "verified", "market_data_date": "2026-07-06"},
            ),
        )


def test_history_store_crud(tmp_path: Path):
    db_file = tmp_path / "test_history.db"
    store = RunHistoryStore(db_path=db_file)

    # 1. Test create_run
    store.create_run(
        run_id="test_run_1",
        ticker="AAPL",
        analysis_date="2026-07-07",
        asset_type="stock",
        selected_analysts=("market", "news"),
        llm_provider="openai",
        research_depth=1,
    )

    run = store.get_run("test_run_1")
    assert run is not None
    assert run["run_id"] == "test_run_1"
    assert run["ticker"] == "AAPL"
    assert run["status"] == "pending"
    assert run["decision_status"] == "unavailable"

    # 2. Test mark_started
    store.mark_started("test_run_1")
    run = store.get_run("test_run_1")
    assert run["status"] == "running"
    assert run["started_at"] is not None

    # 3. Test add_event and deduplication
    ev1 = AnalysisEvent(type="message", run_id="test_run_1", agent="Market Analyst", content="Ev1 content")
    store.add_event("test_run_1", ev1)
    
    # Try duplicate event
    store.add_event("test_run_1", ev1)

    run = store.get_run("test_run_1")
    assert len(run["events"]) == 1
    assert run["events"][0]["content"] == "Ev1 content"

    # 4. Test mark_finished
    store.mark_finished("test_run_1", "completed")
    run = store.get_run("test_run_1")
    assert run["status"] == "completed"
    assert run["finished_at"] is not None

    # 5. Test list_runs
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0]["run_id"] == "test_run_1"

    with store._conn() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000


def test_history_persists_review_required_as_no_decision(tmp_path: Path):
    store = RunHistoryStore(tmp_path / "review.db")
    store.create_run(
        run_id="review-run", ticker="NVDA", analysis_date="2026-07-10",
        asset_type="stock", selected_analysts=("market",),
        llm_provider="openai", research_depth=1,
    )
    store.add_event("review-run", AnalysisEvent(
        type="run_completed",
        run_id="review-run",
        content={"decision_status": "review_required", "decision": "NO_DECISION"},
    ))
    run = store.get_run("review-run")
    assert run["status"] == "review_required"
    assert run["decision_status"] == "review_required"


def test_analysis_runner_binds_run_id_to_vendor_audit(monkeypatch, tmp_path: Path):
    from tradingagents.runtime import analysis_runner, history as history_module
    from tradingagents.dataflows import interface
    from tradingagents.dataflows import vendor_verification as verification_module
    from tradingagents.dataflows.vendor_verification import VendorVerificationStore

    store = RunHistoryStore(tmp_path / "runner.db")
    monkeypatch.setattr(history_module, "history_store", store)
    monkeypatch.setattr(
        verification_module,
        "vendor_verification_store",
        VendorVerificationStore(tmp_path / "runner.db"),
    )
    monkeypatch.setattr(
        interface, "get_vendor", lambda category, method: "primary, test_vendor"
    )
    payload = "Date,Open,High,Low,Close,Volume\n2026-07-10,100,105,99,103,1000\n"

    def fake_impl(request):
        interface.route_to_vendor(
            "get_stock_data", "NVDA", "2026-07-01", "2026-07-10"
        )
        yield AnalysisEvent(
            type="run_completed",
            run_id=request.run_id,
            content={"decision": "Hold"},
        )

    monkeypatch.setattr(analysis_runner, "_run_analysis_stream_impl", fake_impl)
    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {"get_stock_data": {
            "primary": mock.Mock(
                side_effect=interface.NoMarketDataError(
                    "NVDA", detail="primary has no complete row"
                )
            ),
            "test_vendor": lambda *args: payload,
        }},
        clear=False,
    ):
        request = AnalysisRequest(
            ticker="NVDA",
            analysis_date="2026-07-10",
            selected_analysts=("market",),
            run_id="runner-audit",
        )
        list(analysis_runner.run_analysis_stream(request))

    calls = store.get_vendor_calls("runner-audit")
    assert len(calls) == 2
    assert all(call["run_id"] == "runner-audit" for call in calls)
    assert [(call["status"], call["selected"]) for call in calls] == [
        ("no_data", 0), ("available", 1)
    ]
    run = store.get_run("runner-audit")
    vendor_events = [event for event in run["events"] if event["type"] == "vendor_attempt"]
    assert len(vendor_events) == 2
    assert {event["content"]["call_id"] for event in vendor_events} == {
        calls[0]["call_id"]
    }
    assert "primary has no complete row" in vendor_events[0]["content"]["error_detail"]
    assert vendor_events[1]["content"]["selected"] is True
    assert run["data_status"] == "degraded"


def test_vendor_summary_distinguishes_fallback_and_unavailable(tmp_path: Path):
    store = RunHistoryStore(tmp_path / "summary.db")
    store.create_run(
        "summary-run", "NVDA", "2026-07-10", "stock", ["market"], "test", 1
    )
    base = {
        "run_id": "summary-run", "category": "core_stock_apis",
        "method": "get_stock_data", "agent": "Market Analyst", "symbol": "NVDA",
        "arguments_json": "[]", "latency_ms": 1, "result_summary": None,
        "result_hash": None, "calculation_start": None, "requested_end": None,
        "data_latest_date": None, "started_at": "2026-07-14T00:00:00+00:00",
        "finished_at": "2026-07-14T00:00:01+00:00",
    }
    store.add_vendor_call({
        **base, "call_id": "fallback-call", "attempt": 1, "vendor": "primary",
        "status": "rate_limited", "selected": False,
        "error_type": "VendorRateLimitError", "error_detail": "HTTP 429",
    })
    store.add_vendor_call({
        **base, "call_id": "fallback-call", "attempt": 2, "vendor": "fallback",
        "status": "available", "selected": True,
        "error_type": None, "error_detail": None, "result_hash": "abc",
    })
    store.add_vendor_call({
        **base, "call_id": "missing-call", "attempt": 1, "vendor": "only",
        "category": "news_data", "method": "get_news", "status": "no_data",
        "selected": False, "error_type": "NoMarketDataError",
        "error_detail": "no articles before cutoff",
    })

    summary = store.get_vendor_summary("summary-run")
    assert summary["data_status"] == "degraded"
    assert summary["fallback_domains"] == ["core_stock_apis"]
    assert summary["unavailable_domains"] == ["news_data"]
    assert summary["partially_available_domains"] == []
    assert summary["attempt_count"] == 3
    assert summary["trajectories"] == [
        {
            "call_id": "fallback-call", "category": "core_stock_apis",
            "method": "get_stock_data", "agent": "Market Analyst", "symbol": "NVDA",
            "status": "degraded", "selected_vendor": "fallback", "attempt_count": 2,
            "attempts": [
                {
                    "attempt": 1, "vendor": "primary", "status": "rate_limited",
                    "selected": False, "error_type": "VendorRateLimitError",
                    "error_detail": "HTTP 429",
                },
                {
                    "attempt": 2, "vendor": "fallback", "status": "available",
                    "selected": True, "error_type": None, "error_detail": None,
                },
            ],
        },
        {
            "call_id": "missing-call", "category": "news_data", "method": "get_news",
            "agent": "Market Analyst", "symbol": "NVDA", "status": "unavailable",
            "selected_vendor": None, "attempt_count": 1,
            "attempts": [{
                "attempt": 1, "vendor": "only", "status": "no_data",
                "selected": False, "error_type": "NoMarketDataError",
                "error_detail": "no articles before cutoff",
            }],
        },
    ]


def test_vendor_summary_treats_all_available_supporting_call_as_available():
    calls = [{
        "call_id": "reconciliation:get_cashflow:1",
        "attempt": 1,
        "vendor": "longbridge_mcp",
        "category": "fundamental_data",
        "method": "get_cashflow",
        "agent": "Fundamentals Analyst",
        "symbol": "NVDA",
        "status": "available",
        "selected": False,
    }]

    summary = summarize_vendor_calls(calls)

    assert summary["data_status"] == "available"
    assert summary["unavailable_domains"] == []
    assert summary["partially_available_domains"] == []
    assert summary["trajectories"] == []


def test_vendor_summary_reports_mixed_domain_as_partial_not_unavailable():
    calls = [
        {
            "call_id": "prediction-fed", "attempt": 1, "vendor": "polymarket",
            "category": "prediction_markets", "method": "get_prediction_markets",
            "agent": "News Analyst", "symbol": "Fed rate cut 2026",
            "status": "available", "selected": True,
            "error_type": None, "error_detail": None,
        },
        {
            "call_id": "prediction-earnings", "attempt": 1,
            "vendor": "polymarket", "category": "prediction_markets",
            "method": "get_prediction_markets", "agent": "News Analyst",
            "symbol": "NVDA Nvidia earnings", "status": "invalid",
            "selected": False, "error_type": "NoMarketDataError",
            "error_detail": "no markets passed expiry validation",
        },
    ]

    summary = summarize_vendor_calls(calls)

    assert summary["data_status"] == "degraded"
    assert summary["partially_available_domains"] == ["prediction_markets"]
    assert summary["unavailable_domains"] == []
    assert summary["trajectories"][0]["symbol"] == "NVDA Nvidia earnings"
    assert summary["trajectories"][0]["attempts"] == [{
        "attempt": 1, "vendor": "polymarket", "status": "invalid",
        "selected": False, "error_type": "NoMarketDataError",
        "error_detail": "no markets passed expiry validation",
    }]


def test_longitudinal_context_is_structured_audited_and_cutoff_safe(
    tmp_path, monkeypatch
):
    store = RunHistoryStore(tmp_path / "runs.db")
    store.create_run(
        "evaluated-nvda", "NVDA", "2026-07-01", "stock", ["market"],
        "minimax-cn", 1, architecture_version="baseline",
    )
    store.add_event("evaluated-nvda", AnalysisEvent(
        type="run_completed",
        run_id="evaluated-nvda",
        timestamp="2026-07-01T21:00:00+00:00",
        content={
            "decision": "Rating: Buy",
            "decision_status": "validated",
            "decision_as_of": "2026-07-01T21:00:00+00:00",
        },
    ))
    store.add_decision_evaluation({
        "run_id": "evaluated-nvda",
        "horizon_sessions": 5,
        "ticker": "NVDA",
        "analysis_date": "2026-07-01",
        "rating": "Buy",
        "benchmark": "SPY",
        "entry_date": "2026-07-02",
        "exit_date": "2026-07-09",
        "stock_entry_close": 100.0,
        "stock_exit_close": 105.0,
        "benchmark_entry_close": 500.0,
        "benchmark_exit_close": 510.0,
        "stock_entry_source_id": "ohlcv:test:stock-entry:2026-07-02",
        "stock_exit_source_id": "ohlcv:test:stock-exit:2026-07-09",
        "benchmark_entry_source_id": "ohlcv:test:bench-entry:2026-07-02",
        "benchmark_exit_source_id": "ohlcv:test:bench-exit:2026-07-09",
        "decision_as_of": "2026-07-01T21:00:00+00:00",
        "decision_timezone": "America/New_York",
        "entry_cutoff_date": "2026-07-01",
        "raw_return": 0.05,
        "benchmark_return": 0.02,
        "alpha_return": 0.03,
        "exposure": 1.0,
        "directional_hit": True,
        "score": 0.03,
        "architecture_version": "baseline",
        "evaluated_at": "2026-07-10T20:00:00+00:00",
    })

    assert store.get_longitudinal_context(
        "NVDA", information_cutoff="2026-07-10T15:59:59-04:00"
    ) == ""
    context = json.loads(store.get_longitudinal_context(
        "NVDA", information_cutoff="2026-07-10T16:00:01-04:00"
    ))
    assert context["schema"] == "tradingagents/audited-longitudinal-outcomes/v8"
    assert context["same_symbol_outcomes"][0]["run_id"] == "evaluated-nvda"
    assert context["same_symbol_outcomes"][0]["directional_hit"] is True
    assert context["same_symbol_outcomes"][0]["measurement_version"] == "post-decision-day-close-v1"
    assert context["same_symbol_outcomes"][0]["analysis_data_status"] == "not_observed"
    assert context["same_symbol_outcomes"][0]["analysis_evidence_complete"] == 0
    assert context["same_symbol_outcomes"][0]["architecture_input_complete"] == 0
    assert context["same_symbol_outcomes"][0]["market_data_date"] is None
    assert "reflection" not in context["same_symbol_outcomes"][0]
    rollup = context["same_symbol_architecture_rollups"][0]
    assert rollup["sample_count"] == 1
    assert "runtime_seconds_sample_count" not in rollup

    stored = store.list_decision_evaluations()[0]
    rows = [
        {
            **stored,
            "run_id": f"same-{index}",
            "analysis_date": f"2026-07-0{index + 1}",
            "evaluated_at": f"2026-07-{12 - index:02d}T20:00:00+00:00",
        }
        for index in range(3)
    ]
    rows.append({
        **stored,
        "run_id": "cross-1",
        "ticker": "AAPL",
        "evaluated_at": "2026-07-09T20:00:00+00:00",
    })
    query_options = []

    def fake_list_decision_evaluations(**kwargs):
        query_options.append(kwargs)
        return rows[:3] if kwargs.get("ticker") else rows[3:]

    monkeypatch.setattr(
        store,
        "list_decision_evaluations",
        fake_list_decision_evaluations,
    )
    compact = json.loads(store.get_longitudinal_context(
        "NVDA",
        same_symbol_limit=1,
        cross_symbol_limit=1,
    ))
    assert compact["selection"] == {
        "order": "evaluated_at_descending",
        "scan_limit": 5000,
        "same_symbol_rollup_scope": "all_scanned_same_symbol_outcomes",
        "same_symbol_scanned_count": 3,
        "same_symbol_included_count": 1,
        "cross_symbol_scanned_count": 1,
        "cross_symbol_included_count": 1,
    }
    assert len(compact["same_symbol_outcomes"]) == 1
    assert len(compact["cross_symbol_outcomes"]) == 1
    assert compact["same_symbol_architecture_rollups"][0]["sample_count"] == 3
    assert query_options == [
        {
            "ticker": "NVDA",
            "limit": 5000,
            "include_runtime_metrics": False,
            "evaluated_before": None,
        },
        {
            "exclude_ticker": "NVDA",
            "limit": 5000,
            "include_runtime_metrics": False,
            "evaluated_before": None,
        },
    ]
