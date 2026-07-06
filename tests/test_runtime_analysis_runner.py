from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage

from tradingagents.runtime import AnalysisRequest, run_analysis_once, run_analysis_stream
from tradingagents.runtime.config_builder import build_runtime_config


class FakePropagator:
    def create_initial_state(self, ticker, analysis_date, **kwargs):
        return {
            "company_of_interest": ticker,
            "trade_date": analysis_date,
            **kwargs,
        }

    def get_graph_args(self):
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
        }


class FakeMemoryLog:
    def __init__(self):
        self.decisions = []

    def store_decision(self, **kwargs):
        self.decisions.append(kwargs)


class FakeTradingAgentsGraph:
    def __init__(self, selected_analysts, config, debug=False):
        self.selected_analysts = selected_analysts
        self.config = config
        self.debug = debug
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
    assert result.final_state["final_trade_decision"] == "Hold"
    assert result.report_path is not None
    assert result.report_path.exists()
