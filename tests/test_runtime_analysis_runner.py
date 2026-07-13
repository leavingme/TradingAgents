from pathlib import Path
import pytest

from langchain_core.messages import AIMessage, ToolMessage

from tradingagents.runtime import AnalysisRequest, run_analysis_once, run_analysis_stream
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

    def _resolve_pending_entries(self, ticker):
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

    monkeypatch.setattr(analysis_runner, "TradingAgentsGraph", FakeTradingAgentsGraph)

    request = AnalysisRequest(
        ticker="NVDA",
        analysis_date="2026-07-05",
        selected_analysts=("market",),
        report_dir=tmp_path / "reports",
        run_id="run-1",
    )

    events = list(run_analysis_stream(request))

    assert events[0].type == "run_started"
    assert any(event.type == "message" for event in events)
    assert any(event.type == "tool_call" for event in events)
    assert any(
        event.type == "report_section"
        and isinstance(event.content, dict)
        and event.content["section"] == "market_report"
        for event in events
    )
    completed = events[-1]
    assert completed.type == "run_completed"
    assert isinstance(completed.content, dict)
    assert completed.content["decision"] == "Hold"
    assert Path(completed.content["report_path"]).exists()


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
