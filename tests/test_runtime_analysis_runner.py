import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from langchain_core.messages import AIMessage, ToolMessage

from tradingagents.runtime import (
    AnalysisEvent,
    AnalysisExecutionError,
    AnalysisRequest,
    run_analysis_once,
    run_analysis_stream,
)
from tradingagents.runtime.config_builder import build_runtime_config


@pytest.fixture(autouse=True)
def trusted_snapshot(monkeypatch):
    from tradingagents.dataflows import market_data_validator

    monkeypatch.setattr(
        market_data_validator,
        "verified_snapshot_dict",
        lambda symbol, date: {
            "symbol": symbol, "market_date": date, "close": 100.0, "atr": 5.0,
            "vendor_call_id": "test-call", "calculation_start": "2023-07-06",
            "row_count": 750,
        },
    )


class FakePropagator:
    def create_initial_state(self, ticker, analysis_date, **kwargs):
        return {
            "company_of_interest": ticker,
            "trade_date": analysis_date,
            **kwargs,
        }

    def get_graph_args(self, callbacks=None):
        return {}


class FakeCompiledGraph:
    def stream(self, init_state, **kwargs):
        yield {
            "messages": [
                AIMessage(
                    content="market message",
                    id="msg-1",
                    tool_calls=[
                        {
                            "name": "get_stock_data",
                            "args": {"symbol": init_state["company_of_interest"]},
                            "id": "tool-1",
                        }
                    ],
                )
            ],
            "market_report": "market report",
        }
        yield {
            "messages": [ToolMessage(content="tool output", tool_call_id="tool-1")],
            "investment_debate_state": {
                "bull_history": "bull case",
                "bear_history": "bear case",
                "judge_decision": "research decision",
            },
        }
        yield {
            "messages": [],
            "trader_investment_plan": "trader plan",
            "risk_debate_state": {
                "aggressive_history": "risk upside",
                "conservative_history": "risk downside",
                "neutral_history": "risk neutral",
                "judge_decision": "final decision",
            },
            "final_trade_decision": "Hold",
            "decision_status": "validated",
        }


class FailingCompiledGraph:
    def stream(self, init_state, **kwargs):
        from tradingagents.dataflows.errors import NoUsableFinancialDataError

        raise NoUsableFinancialDataError(
            init_state["company_of_interest"], "income_statement", "missing currency"
        )
        yield  # pragma: no cover


class FakeMemoryLog:
    def __init__(self):
        self.decisions = []

    def store_decision(self, **kwargs):
        self.decisions.append(kwargs)


class FakeTradingAgentsGraph:
    def __init__(self, selected_analysts, config, debug=False, callbacks=None):
        self.selected_analysts = selected_analysts
        self.config = config
        self.debug = debug
        self.callbacks = callbacks or []
        self.propagator = FakePropagator()
        self.graph = FakeCompiledGraph()
        self.workflow = None
        self.memory_log = FakeMemoryLog()
        self.logged = []

    def _resolve_pending_entries(self, ticker, as_of_date=None):
        self.resolved = ticker

    def resolve_instrument_context(self, ticker, asset_type):
        return f"{ticker}:{asset_type}"

    def _log_state(self, analysis_date, final_state):
        self.logged.append((analysis_date, final_state))


def test_build_runtime_config_applies_explicit_request_fields(tmp_path):
    request = AnalysisRequest(
        ticker="NVDA",
        analysis_date="2026-07-05",
        selected_analysts=("news", "market"),
        llm_provider="MiniMax-CN",
        quick_think_llm="MiniMax-M3",
        deep_think_llm="MiniMax-M3",
        research_depth=2,
        checkpoint_enabled=True,
        results_dir=tmp_path,
    )

    config = build_runtime_config(request)

    assert config["llm_provider"] == "minimax-cn"
    assert config["quick_think_llm"] == "MiniMax-M3"
    assert config["deep_think_llm"] == "MiniMax-M3"
    assert config["max_debate_rounds"] == 2
    assert config["max_risk_discuss_rounds"] == 2
    assert config["checkpoint_enabled"] is True
    assert config["results_dir"] == str(tmp_path)


def test_runtime_config_rejects_per_run_risk_policy_override():
    request = AnalysisRequest(
        ticker="NVDA",
        analysis_date="2026-07-05",
        config_overrides={"trade_risk_policy": {"max_portfolio_risk_pct": 99.0}},
    )
    with pytest.raises(ValueError, match="server-owned"):
        build_runtime_config(request)


def test_run_analysis_stream_emits_events_and_writes_report(monkeypatch, tmp_path):
    from tradingagents.runtime import analysis_runner
    from tradingagents.runtime.history import history_store
    from tradingagents.dataflows import market_data_validator

    monkeypatch.setattr(analysis_runner, "TradingAgentsGraph", FakeTradingAgentsGraph)
    monkeypatch.setattr(
        market_data_validator,
        "verified_snapshot_dict",
        lambda symbol, date: {
            "symbol": symbol,
            "market_date": "2026-07-03",
            "close": 100.0,
            "atr": 5.0,
            "vendor_call_id": "test-call",
            "calculation_start": "2023-07-06",
            "row_count": 750,
        },
    )

    request = AnalysisRequest(
        ticker="NVDA",
        analysis_date="2026-07-05",
        selected_analysts=("market",),
        report_dir=tmp_path / "reports",
        run_id="run-1",
    )

    events = list(run_analysis_stream(request))

    assert events[0].type == "run_started"
    assert events[0].content["market_data_date"] is None
    assert events[0].content["market_data_status"] == "pending_verification"
    assert events[0].content["analysis_mode"] == "live"
    assert events[0].content["information_cutoff"] == "live_at_call_time"
    assert any(event.type == "message" for event in events)
    assert any(event.type == "tool_call" for event in events)
    assert any(
        event.type == "report_section"
        and isinstance(event.content, dict)
        and event.content["section"] == "market_report"
        for event in events
    )
    stats = [event.content for event in events if event.type == "stats"]
    assert stats
    assert stats[-1] == {
        "llm_calls": 0,
        "tool_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }
    completed = events[-1]
    assert completed.type == "run_completed"
    assert isinstance(completed.content, dict)
    assert completed.content["decision"] == "Hold"
    assert completed.content["decision_as_of"] == completed.timestamp
    assert completed.content["market_data_date"] == "2026-07-03"
    assert completed.content["architecture_input_schema"] == (
        "tradingagents/research-manager-pre-context-input/v1"
    )
    assert len(completed.content["architecture_input_fingerprint"]) == 64
    assert completed.content["architecture_input_complete"] is False
    assert Path(completed.content["report_path"]).exists()
    assert completed.content["report_sha256"] == hashlib.sha256(
        Path(completed.content["report_path"]).read_bytes()
    ).hexdigest()
    stored = history_store.get_run("run-1")
    assert stored["market_data_date"] == "2026-07-03"
    manifest = json.loads(stored["architecture_manifest_json"])
    assert stored["architecture_version"] == request.architecture_version
    assert len(stored["architecture_fingerprint"]) == 64
    assert manifest["schema"] == "tradingagents/agent-architecture-manifest/v4"
    assert len(manifest["implementation_digest"]) == 64
    assert "tradingagents/agents/**/*.py" in manifest["implementation_digest_scope"]
    assert "tradingagents/automation/**/*.py" not in manifest["implementation_digest_scope"]
    assert manifest["longitudinal_evaluation_policy"]["horizon_sessions"] == 5
    assert manifest["longitudinal_evaluation_policy"]["hold_band"] == 0.02
    assert manifest["longitudinal_evaluation_policy"]["context_schema"] == (
        "tradingagents/audited-longitudinal-outcomes/v8"
    )
    assert manifest["decision_config"]["output_language"] == "Chinese"
    assert manifest["decision_config"]["max_debate_rounds"] == 1
    assert "news_data" in manifest["decision_config"]["data_vendors"]
    assert manifest["decision_config"]["trade_risk_policy"]["max_position_pct"] == 5.0
    assert manifest["llm_provider"] == "minimax-cn"
    assert manifest["quick_think_llm"] == "MiniMax-M3"
    assert manifest["longitudinal_context_mode"] == "research_and_portfolio"
    persisted_terminal = next(
        event for event in stored["events"] if event["type"] == "run_completed"
    )
    assert persisted_terminal["content"]["report_sha256"] == (
        completed.content["report_sha256"]
    )


def test_same_date_runtime_reports_are_immutable_and_run_scoped(
    monkeypatch, tmp_path
):
    from tradingagents.runtime import analysis_runner

    monkeypatch.setattr(analysis_runner, "TradingAgentsGraph", FakeTradingAgentsGraph)
    common = {
        "ticker": "NVDA",
        "analysis_date": "2026-07-05",
        "selected_analysts": ("market",),
        "results_dir": tmp_path,
    }
    first = run_analysis_once(AnalysisRequest(**common, run_id="same-date-first"))
    first_bytes = first.report_path.read_bytes()
    second = run_analysis_once(AnalysisRequest(**common, run_id="same-date-second"))

    assert first.report_path != second.report_path
    assert first.report_path.parent.name == "same-date-first"
    assert second.report_path.parent.name == "same-date-second"
    assert first.report_path.read_bytes() == first_bytes
    assert first.report_path.exists()
    assert second.report_path.exists()


def test_unsafe_run_id_cannot_escape_report_root(tmp_path):
    from tradingagents.reporting import run_report_dir

    report_dir = run_report_dir(
        ticker="NVDA",
        analysis_date="2026-07-05",
        run_id="../../outside report",
        results_dir=tmp_path,
        report_dir=tmp_path / "reports",
    )

    assert report_dir.parent == tmp_path / "reports"
    assert report_dir.name.startswith("run-")
    assert ".." not in report_dir.name


def test_exact_market_date_defers_before_graph_and_llm_construction(
    monkeypatch, tmp_path
):
    from tradingagents.runtime import analysis_runner
    from tradingagents.runtime.history import history_store
    from tradingagents.dataflows import market_data_validator

    monkeypatch.setattr(
        analysis_runner,
        "TradingAgentsGraph",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("graph and LLM clients must not be constructed")
        ),
    )
    def stale_snapshot(symbol, date):
        from tradingagents.dataflows.config import get_config

        assert get_config()["data_vendors"]["core_stock_apis"] == "alpha_vantage"
        return {
            "symbol": symbol,
            "market_date": "2026-07-16",
            "close": 100.0,
            "atr": 5.0,
            "vendor_call_id": "settlement-test",
            "calculation_start": "2023-07-17",
            "row_count": 750,
        }

    monkeypatch.setattr(
        market_data_validator, "verified_snapshot_dict", stale_snapshot
    )
    request = AnalysisRequest(
        ticker="NVDA",
        analysis_date="2026-07-17",
        selected_analysts=("market",),
        report_dir=tmp_path / "reports",
        run_id="run-market-data-pending",
        require_exact_market_data_date=True,
        config_overrides={
            "data_vendors": {"core_stock_apis": "alpha_vantage"}
        },
    )

    result = run_analysis_once(request)

    assert result.decision_status == "market_data_pending"
    assert result.decision is None
    assert not any(event.type == "run_completed" for event in result.events)
    stats = [event.content for event in result.events if event.type == "stats"]
    assert stats == [{
        "llm_calls": 0,
        "tool_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }]
    pending = result.events[-1]
    assert pending.type == "market_data_status"
    assert pending.content["status"] == "pending_provider_settlement"
    assert pending.content["market_data_date"] == "2026-07-16"
    stored = history_store.get_run(request.run_id)
    assert stored["status"] == "market_data_pending"
    assert stored["decision_status"] == "market_data_pending"


def test_exact_market_date_runs_when_verified_candle_matches(monkeypatch, tmp_path):
    from tradingagents.runtime import analysis_runner

    monkeypatch.setattr(analysis_runner, "TradingAgentsGraph", FakeTradingAgentsGraph)
    request = AnalysisRequest(
        ticker="NVDA",
        analysis_date="2026-07-17",
        selected_analysts=("market",),
        report_dir=tmp_path / "reports",
        run_id="run-exact-market-data-ready",
        require_exact_market_data_date=True,
    )

    result = run_analysis_once(request)

    assert result.decision_status == "validated"
    assert result.decision == "Hold"
    completed = next(event for event in result.events if event.type == "run_completed")
    assert completed.content["market_data_date"] == "2026-07-17"


def test_canonical_runtime_injects_sqlite_longitudinal_context(monkeypatch, tmp_path):
    from tradingagents.runtime import analysis_runner
    from tradingagents.runtime.history import history_store

    seen = {}

    class CapturingCompiledGraph(FakeCompiledGraph):
        def stream(self, init_state, **kwargs):
            seen.update(init_state)
            yield from super().stream(init_state, **kwargs)

    class CapturingGraph(FakeTradingAgentsGraph):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.graph = CapturingCompiledGraph()

    monkeypatch.setattr(analysis_runner, "TradingAgentsGraph", CapturingGraph)
    context_payload = {
        "schema": "tradingagents/audited-longitudinal-outcomes/v8",
        "selection": {
            "same_symbol_scanned_count": 3,
            "same_symbol_included_count": 2,
            "cross_symbol_scanned_count": 1,
            "cross_symbol_included_count": 1,
        },
        "same_symbol_architecture_rollups": [{"sample_count": 3}],
    }
    context_json = json.dumps(context_payload, separators=(",", ":"))
    monkeypatch.setattr(
        history_store,
        "get_longitudinal_context",
        lambda ticker, information_cutoff=None: context_json,
    )
    events = list(run_analysis_stream(AnalysisRequest(
        ticker="NVDA",
        analysis_date="2026-07-05",
        selected_analysts=("market",),
        report_dir=tmp_path / "reports",
        run_id="runtime-longitudinal-context",
    )))
    assert seen["past_context"] == context_json
    status = next(
        event for event in events if event.type == "longitudinal_context_status"
    )
    assert status.content == {
        "mode": "research_and_portfolio",
        "information_cutoff": None,
        "schema": "tradingagents/audited-longitudinal-outcomes/v8",
        "same_symbol_scanned_count": 3,
        "same_symbol_included_count": 2,
        "cross_symbol_scanned_count": 1,
        "cross_symbol_included_count": 1,
        "same_symbol_architecture_rollup_count": 1,
        "status": "loaded",
    }


def test_live_runtime_injects_outcome_settled_in_same_run(monkeypatch, tmp_path):
    from tradingagents.evaluation import OutcomeMeasurement
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.runtime import analysis_runner
    from tradingagents.runtime.history import history_store

    poisoned_run_id = "poisoned-validated-history"
    history_store.create_run(
        poisoned_run_id,
        "NVDA",
        "2026-06-30",
        "stock",
        ["market"],
        "minimax-cn",
        1,
        architecture_version="legacy-invalid",
        architecture_fingerprint="b" * 64,
    )
    history_store.add_event(
        poisoned_run_id,
        AnalysisEvent(
            type="run_completed",
            run_id=poisoned_run_id,
            timestamp="2026-06-30T21:00:00+00:00",
            content={"decision_status": "validated"},
        ),
    )

    prior_run_id = "prior-outcome-matures-today"
    architecture_fingerprint = "a" * 64
    history_store.create_run(
        prior_run_id,
        "NVDA",
        "2026-07-01",
        "stock",
        ["market"],
        "minimax-cn",
        1,
        architecture_version="baseline",
        architecture_fingerprint=architecture_fingerprint,
    )
    history_store.mark_started(
        prior_run_id,
        started_at="2026-07-01T20:00:00+00:00",
    )
    history_store.update_run_market_data_date(prior_run_id, "2026-06-30")
    history_store.add_event(
        prior_run_id,
        AnalysisEvent(
            type="run_completed",
            run_id=prior_run_id,
            timestamp="2026-07-01T21:00:00+00:00",
            content={
                "decision": "Rating: Buy",
                "decision_status": "validated",
                "decision_as_of": "2026-07-01T21:00:00+00:00",
                "architecture_input_schema": (
                    "tradingagents/research-manager-pre-context-input/v1"
                ),
                "architecture_input_fingerprint": "prior-upstream-state",
                "architecture_input_complete": True,
            },
        ),
    )
    history_store.mark_finished(
        prior_run_id,
        "completed",
        finished_at="2026-07-01T21:01:00+00:00",
    )

    captured_state = {}

    class CapturingCompiledGraph(FakeCompiledGraph):
        def stream(self, init_state, **kwargs):
            captured_state.update(init_state)
            yield from super().stream(init_state, **kwargs)

    class SameRunSettlementGraph(FakeTradingAgentsGraph):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.graph = CapturingCompiledGraph()
            self.memory_log.get_pending_entries = lambda: []

        def _resolve_benchmark(self, ticker):
            return "SPY"

        def _fetch_returns(self, ticker, trade_date, **kwargs):
            assert ticker == "NVDA"
            assert trade_date == "2026-07-01"
            assert kwargs["as_of_date"] == "2026-07-10"
            assert kwargs["decision_as_of"] == "2026-07-01T21:00:00+00:00"
            return OutcomeMeasurement(
                raw_return=0.05,
                benchmark_return=0.02,
                alpha_return=0.03,
                horizon_sessions=5,
                entry_date="2026-07-02",
                exit_date="2026-07-09",
                stock_entry_close=100.0,
                stock_exit_close=105.0,
                benchmark_entry_close=500.0,
                benchmark_exit_close=510.0,
                stock_entry_source_id="ohlcv:test:stock-entry:2026-07-02",
                stock_exit_source_id="ohlcv:test:stock-exit:2026-07-09",
                benchmark_entry_source_id="ohlcv:test:bench-entry:2026-07-02",
                benchmark_exit_source_id="ohlcv:test:bench-exit:2026-07-09",
                decision_as_of="2026-07-01T21:00:00+00:00",
                decision_timezone="America/New_York",
                entry_cutoff_date="2026-07-01",
            )

        def _resolve_pending_entries(self, ticker, as_of_date=None):
            return TradingAgentsGraph._resolve_pending_entries(
                self,
                ticker,
                as_of_date=as_of_date,
            )

    monkeypatch.setattr(analysis_runner, "TradingAgentsGraph", SameRunSettlementGraph)
    current_run_id = "runtime-same-run-outcome-injection"
    events = list(
        run_analysis_stream(
            AnalysisRequest(
                ticker="NVDA",
                analysis_date="2026-07-10",
                selected_analysts=("market",),
                report_dir=tmp_path / "reports",
                run_id=current_run_id,
            )
        )
    )

    evaluations = history_store.list_decision_evaluations(
        ticker="NVDA",
        include_runtime_metrics=False,
    )
    assert len(evaluations) == 1
    assert evaluations[0]["run_id"] == prior_run_id
    assert evaluations[0]["evaluated_by_run_id"] == current_run_id
    blocked = next(
        row
        for row in history_store.list_unevaluated_validated_runs(ticker="NVDA")
        if row["run_id"] == poisoned_run_id
    )
    assert blocked["settlement_issue_code"] == "validated_decision_missing"
    assert any(
        event.type == "run_completed"
        and event.content.get("decision_status") == "validated"
        for event in events
    )
    context = json.loads(captured_state["past_context"])
    assert context["selection"]["same_symbol_scanned_count"] == 1
    assert context["selection"]["same_symbol_included_count"] == 1
    assert context["same_symbol_outcomes"][0]["run_id"] == prior_run_id
    assert context["same_symbol_outcomes"][0]["score"] == 0.03
    status = next(
        event for event in events if event.type == "longitudinal_context_status"
    )
    assert status.content["status"] == "loaded"
    assert status.content["same_symbol_scanned_count"] == 1
    assert status.content["same_symbol_included_count"] == 1
    persisted_status = next(
        event
        for event in history_store.get_run(current_run_id)["events"]
        if event["type"] == "longitudinal_context_status"
    )
    assert persisted_status["content"]["same_symbol_scanned_count"] == 1
    assert persisted_status["content"]["same_symbol_included_count"] == 1


def test_runtime_rejects_malformed_longitudinal_context(monkeypatch, tmp_path):
    from tradingagents.runtime import analysis_runner
    from tradingagents.runtime.history import history_store

    monkeypatch.setattr(analysis_runner, "TradingAgentsGraph", FakeTradingAgentsGraph)
    monkeypatch.setattr(
        history_store,
        "get_longitudinal_context",
        lambda ticker, information_cutoff=None: '{"schema":"untrusted"}',
    )

    events = list(run_analysis_stream(AnalysisRequest(
        ticker="NVDA",
        analysis_date="2026-07-17",
        selected_analysts=("market",),
        report_dir=tmp_path / "reports",
        run_id="runtime-malformed-longitudinal-context",
    )))

    error = next(event for event in events if event.type == "error")
    assert error.content["error_type"] == "ValueError"
    assert "unsupported schema" in error.content["error"]


def test_run_analysis_stream_binds_and_resets_analysis_date(monkeypatch, tmp_path):
    from tradingagents.runtime import analysis_runner
    from tradingagents.runtime.audit_context import (
        current_analysis_date,
        current_analysis_mode,
        current_information_cutoff,
    )

    seen = []

    class ContextCompiledGraph(FakeCompiledGraph):
        def stream(self, init_state, **kwargs):
            seen.append((
                current_analysis_date(),
                current_analysis_mode(),
                current_information_cutoff(),
            ))
            yield from super().stream(init_state, **kwargs)

    class ContextTradingAgentsGraph(FakeTradingAgentsGraph):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.graph = ContextCompiledGraph()

    monkeypatch.setattr(
        analysis_runner, "TradingAgentsGraph", ContextTradingAgentsGraph
    )
    list(run_analysis_stream(AnalysisRequest(
        ticker="NVDA",
        analysis_date="2026-07-05",
        selected_analysts=("market",),
        report_dir=tmp_path / "reports",
        run_id="run-analysis-date-context",
    )))

    assert seen == [("2026-07-05", "live", None)]
    assert current_analysis_date() is None
    assert current_analysis_mode() == "live"
    assert current_information_cutoff() is None


def test_point_in_time_request_requires_timezone_aware_cutoff():
    with pytest.raises(ValueError, match="requires information_cutoff"):
        AnalysisRequest(
            ticker="NVDA",
            analysis_date="2026-07-10",
            analysis_mode="point_in_time",
        )
    with pytest.raises(ValueError, match="include a timezone"):
        AnalysisRequest(
            ticker="NVDA",
            analysis_date="2026-07-10",
            analysis_mode="point_in_time",
            information_cutoff="2026-07-10T20:00:00",
        )
    request = AnalysisRequest(
        ticker="NVDA",
        analysis_date="2026-07-10",
        analysis_mode="point_in_time",
        information_cutoff="2026-07-10T20:00:00+00:00",
    )
    assert request.information_cutoff == "2026-07-10T20:00:00+00:00"


def test_live_request_uses_market_date_without_backdating_information():
    request = AnalysisRequest(
        ticker="NVDA",
        analysis_date="2026-07-10",
        analysis_mode="live",
    )
    assert request.analysis_date == "2026-07-10"
    assert request.information_cutoff is None


def test_agent_statuses_are_monotonic_and_report_updates_are_deduplicated(
    monkeypatch, tmp_path
):
    from tradingagents.runtime import analysis_runner

    monkeypatch.setattr(analysis_runner, "TradingAgentsGraph", FakeTradingAgentsGraph)
    events = list(run_analysis_stream(AnalysisRequest(
        ticker="NVDA",
        analysis_date="2026-07-05",
        selected_analysts=("market",),
        report_dir=tmp_path / "reports",
        run_id="run-workflow-status",
    )))

    statuses: dict[str, list[str]] = {}
    for event in events:
        if event.type == "agent_status":
            statuses.setdefault(event.agent, []).append(event.content["status"])

    assert statuses["Research Manager"] == ["pending", "in_progress", "completed"]
    assert statuses["Trader"] == ["pending", "in_progress", "completed"]
    assert statuses["Portfolio Manager"] == ["pending", "in_progress", "completed"]
    assert statuses["Bull Researcher"][-1] == "completed"
    assert statuses["Bear Researcher"][-1] == "completed"
    for transitions in statuses.values():
        completed_at = [i for i, value in enumerate(transitions) if value == "completed"]
        if completed_at:
            assert all(value == "completed" for value in transitions[completed_at[0]:])

    sections = [
        event.content["section"]
        for event in events
        if event.type == "report_section"
    ]
    assert len(sections) == len(set(sections))


def test_runtime_persists_only_coalesced_report_section_versions(monkeypatch):
    from tradingagents.runtime import analysis_runner, history_store

    def fake_stream(request):
        yield AnalysisEvent(type="run_started", run_id=request.run_id, content={})
        for version in range(100):
            yield AnalysisEvent(
                type="report_section",
                run_id=request.run_id,
                agent="Researcher",
                content={"section": "debate", "text": f"version-{version}"},
            )
        yield AnalysisEvent(
            type="run_completed",
            run_id=request.run_id,
            content={"decision_status": "validated"},
        )

    monkeypatch.setenv("TRADINGAGENTS_REPORT_SECTION_THROTTLE_MS", "60000")
    monkeypatch.setattr(analysis_runner, "_run_analysis_stream_impl", fake_stream)
    events = list(run_analysis_stream(AnalysisRequest(
        ticker="NVDA",
        analysis_date="2026-07-05",
        run_id="run-coalesced-reports",
    )))

    reports = [event for event in events if event.type == "report_section"]
    persisted = history_store.get_run("run-coalesced-reports")
    persisted_reports = [
        event for event in persisted["events"] if event["type"] == "report_section"
    ]
    assert len(reports) == len(persisted_reports) == 2
    assert reports[-1].content["text"] == "version-99"
    assert persisted_reports[-1]["content"]["text"] == "version-99"


def test_concurrent_runs_coalesce_report_writes_without_sqlite_lock_errors(monkeypatch):
    from tradingagents.runtime import analysis_runner, history_store

    def fake_stream(request):
        yield AnalysisEvent(type="run_started", run_id=request.run_id, content={})
        for version in range(100):
            yield AnalysisEvent(
                type="report_section",
                run_id=request.run_id,
                agent="Researcher",
                content={"section": "debate", "text": f"version-{version}"},
            )
        yield AnalysisEvent(
            type="run_completed",
            run_id=request.run_id,
            content={"decision_status": "validated"},
        )

    monkeypatch.setenv("TRADINGAGENTS_REPORT_SECTION_THROTTLE_MS", "60000")
    monkeypatch.setattr(analysis_runner, "_run_analysis_stream_impl", fake_stream)

    def execute(index):
        return list(run_analysis_stream(AnalysisRequest(
            ticker="NVDA",
            analysis_date="2026-07-05",
            run_id=f"run-concurrent-{index}",
        )))

    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(execute, range(4)))

    assert sum(
        event.type == "report_section" for events in runs for event in events
    ) == 8
    for index in range(4):
        persisted = history_store.get_run(f"run-concurrent-{index}")
        reports = [
            event for event in persisted["events"]
            if event["type"] == "report_section"
        ]
        assert len(reports) == 2
        assert reports[-1]["content"]["text"] == "version-99"


def test_data_validation_error_stops_run_without_report_or_completion(monkeypatch, tmp_path):
    from tradingagents.runtime import analysis_runner

    class FailingTradingAgentsGraph(FakeTradingAgentsGraph):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.graph = FailingCompiledGraph()

    monkeypatch.setattr(analysis_runner, "TradingAgentsGraph", FailingTradingAgentsGraph)
    report_dir = tmp_path / "reports"
    events = list(run_analysis_stream(AnalysisRequest(
        ticker="0700.HK",
        analysis_date="2026-07-10",
        selected_analysts=("fundamentals",),
        report_dir=report_dir,
        run_id="run-financial-gate",
    )))

    assert events[-1].type == "error"
    assert events[-1].content["error_type"] == "NoUsableFinancialDataError"
    assert any(event.type == "stats" for event in events)
    assert not any(event.type == "run_completed" for event in events)
    assert not report_dir.exists()


class FakeStatsHandler:
    def __init__(self):
        self.calls = 0

    def get_stats(self):
        self.calls += 1
        return {
            "llm_calls": self.calls,
            "tool_calls": self.calls + 1,
            "tokens_in": self.calls * 10,
            "tokens_out": self.calls * 20,
        }


def test_run_analysis_stream_emits_callback_stats(monkeypatch, tmp_path):
    from tradingagents.runtime import analysis_runner

    monkeypatch.setattr(analysis_runner, "TradingAgentsGraph", FakeTradingAgentsGraph)

    stats_handler = FakeStatsHandler()
    events = list(
        run_analysis_stream(
            AnalysisRequest(
                ticker="NVDA",
                analysis_date="2026-07-05",
                selected_analysts=("market",),
                report_dir=tmp_path / "reports",
                run_id="run-stats",
                callbacks=(stats_handler,),
            )
        )
    )

    stats_events = [event for event in events if event.type == "stats"]
    assert stats_events
    assert isinstance(stats_events[-1].content, dict)
    assert stats_events[-1].content["llm_calls"] >= 1
    assert stats_events[-1].content["tokens_out"] >= 20


def test_run_analysis_once_returns_final_result(monkeypatch, tmp_path):
    from tradingagents.runtime import analysis_runner

    monkeypatch.setattr(analysis_runner, "TradingAgentsGraph", FakeTradingAgentsGraph)

    result = run_analysis_once(
        AnalysisRequest(
            ticker="NVDA",
            analysis_date="2026-07-05",
            selected_analysts=("market",),
            report_dir=tmp_path / "reports",
            run_id="run-2",
        )
    )

    assert result.run_id == "run-2"
    assert result.decision == "Hold"
    assert result.decision_status == "validated"
    assert result.final_state["final_trade_decision"] == "Hold"
    assert result.report_path is not None
    assert result.report_path.exists()


def test_run_analysis_once_preserves_safe_runtime_error_type(monkeypatch):
    from tradingagents.runtime import analysis_runner

    monkeypatch.setattr(
        analysis_runner,
        "run_analysis_stream",
        lambda request: iter((AnalysisEvent(
            type="error",
            run_id=request.run_id,
            content={
                "error": "credential=sentinel-secret https://example.invalid/v1",
                "error_type": "OutcomeSettlementDataError",
            },
        ),)),
    )

    with pytest.raises(AnalysisExecutionError) as exc_info:
        analysis_runner.run_analysis_once(AnalysisRequest(
            ticker="NVDA", analysis_date="2026-07-05", run_id="typed-error"
        ))

    assert exc_info.value.error_type == "OutcomeSettlementDataError"
    assert "sentinel-secret" not in str(exc_info.value)
    assert "example.invalid" not in str(exc_info.value)


def test_run_analysis_once_rejects_unsafe_error_type(monkeypatch):
    from tradingagents.runtime import analysis_runner

    monkeypatch.setattr(
        analysis_runner,
        "run_analysis_stream",
        lambda request: iter((AnalysisEvent(
            type="error",
            run_id=request.run_id,
            content={"error_type": "BadError credential=sentinel-secret"},
        ),)),
    )

    with pytest.raises(AnalysisExecutionError) as exc_info:
        analysis_runner.run_analysis_once(AnalysisRequest(
            ticker="NVDA", analysis_date="2026-07-05", run_id="unsafe-type"
        ))

    assert exc_info.value.error_type == "RuntimeError"
    assert "sentinel-secret" not in str(exc_info.value)


def test_outcome_settlement_failure_stops_before_agent_and_persists_retryable_status(
    monkeypatch, tmp_path
):
    from tradingagents.graph.trading_graph import OutcomeSettlementDataError
    from tradingagents.runtime import analysis_runner, history_store

    class SettlementFailureGraph(FakeTradingAgentsGraph):
        def _resolve_pending_entries(self, ticker, as_of_date=None):
            raise OutcomeSettlementDataError("ohlcv_unavailable")

    monkeypatch.setattr(analysis_runner, "TradingAgentsGraph", SettlementFailureGraph)
    events = tuple(run_analysis_stream(AnalysisRequest(
        ticker="NVDA",
        analysis_date="2026-07-05",
        selected_analysts=("market",),
        report_dir=tmp_path / "reports",
        run_id="settlement-before-agent",
    )))

    error = next(event for event in events if event.type == "error")
    stats = next(event for event in events if event.type == "stats")
    assert error.content["error_type"] == "OutcomeSettlementDataError"
    assert stats.content["llm_calls"] == 0
    assert not any(event.type == "agent_status" for event in events)
    stored = history_store.get_run("settlement-before-agent")
    assert stored["status"] == "outcome_settlement_pending"
    assert stored["finished_at"] is not None


def test_point_in_time_run_does_not_resolve_future_outcomes(monkeypatch, tmp_path):
    from tradingagents.runtime import analysis_runner

    resolved = []
    monkeypatch.setattr(analysis_runner, "TradingAgentsGraph", FakeTradingAgentsGraph)
    monkeypatch.setattr(
        FakeTradingAgentsGraph,
        "_resolve_pending_entries",
        lambda self, ticker, as_of_date=None: resolved.append((ticker, as_of_date)),
    )
    result = run_analysis_once(
        AnalysisRequest(
            ticker="NVDA",
            analysis_date="2026-07-05",
            analysis_mode="point_in_time",
            information_cutoff="2026-07-05T16:00:00-04:00",
            selected_analysts=("market",),
            report_dir=tmp_path / "reports",
            run_id="historical-no-reflection",
        )
    )
    assert result.decision_status == "validated"
    assert resolved == []


def test_run_analysis_once_returns_no_decision_for_review_required(monkeypatch):
    from tradingagents.runtime import analysis_runner
    from tradingagents.runtime.events import AnalysisEvent

    monkeypatch.setattr(
        analysis_runner,
        "run_analysis_stream",
        lambda request: iter((AnalysisEvent(
            type="run_completed",
            run_id=request.run_id,
            content={
                "decision": "**Decision**: NO_DECISION",
                "decision_status": "review_required",
            },
        ),)),
    )
    result = analysis_runner.run_analysis_once(AnalysisRequest(
        ticker="NVDA", analysis_date="2026-07-05", run_id="review-run"
    ))
    assert result.decision is None
    assert result.decision_status == "review_required"
