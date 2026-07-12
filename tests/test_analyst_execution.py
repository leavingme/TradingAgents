import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import START

from tradingagents.graph.analyst_execution import (
    AnalystWallTimeTracker,
    build_analyst_execution_plan,
    get_initial_analyst_node,
    sync_analyst_tracker_from_chunk,
)
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import GraphSetup, make_analyst_node


class AnalystExecutionPlanTests(unittest.TestCase):
    def test_build_plan_preserves_selected_order(self):
        plan = build_analyst_execution_plan(["news", "market"])

        self.assertEqual([spec.key for spec in plan.specs], ["news", "market"])
        self.assertEqual(plan.specs[0].agent_node, "News Analyst")
        self.assertEqual(plan.specs[0].tool_node, "tools_news")
        self.assertEqual(plan.specs[0].clear_node, "Msg Clear News")

    def test_rejects_unknown_analyst_keys(self):
        with self.assertRaises(ValueError):
            build_analyst_execution_plan(["market", "macro"])

    def test_get_initial_analyst_node_uses_plan_metadata(self):
        plan = build_analyst_execution_plan(["fundamentals", "news"])

        self.assertEqual(
            get_initial_analyst_node(plan),
            "Fundamentals Analyst",
        )

    def test_social_key_displays_as_sentiment_analyst(self):
        # The wire key stays "social" for saved-config back-compat, but the
        # user-visible agent_node label must match the v0.2.5 rename so the
        # wall-time summary and any future consumer of agent_node says
        # "Sentiment Analyst" rather than the legacy "Social Analyst".
        plan = build_analyst_execution_plan(["social"])
        spec = plan.specs[0]
        self.assertEqual(spec.key, "social")
        self.assertEqual(spec.agent_node, "Sentiment Analyst")
        self.assertEqual(spec.report_key, "sentiment_report")


class AnalystWallTimeTrackerTests(unittest.TestCase):
    def test_records_wall_time_when_analyst_completes(self):
        plan = build_analyst_execution_plan(["market", "news"])
        tracker = AnalystWallTimeTracker(plan)

        tracker.mark_started("market", started_at=10.0)
        tracker.mark_completed("market", completed_at=13.5)

        self.assertEqual(tracker.get_wall_times(), {"market": 3.5})

    def test_formats_summary_in_plan_order(self):
        plan = build_analyst_execution_plan(["news", "market"])
        tracker = AnalystWallTimeTracker(plan)

        tracker.mark_started("market", started_at=20.0)
        tracker.mark_completed("market", completed_at=22.25)
        tracker.mark_started("news", started_at=10.0)
        tracker.mark_completed("news", completed_at=14.0)

        self.assertEqual(
            tracker.format_summary(),
            "Analyst wall time: News 4.00s | Market 2.25s",
        )

    def test_syncs_wall_time_from_sequential_chunks(self):
        plan = build_analyst_execution_plan(["market", "news"])
        tracker = AnalystWallTimeTracker(plan)

        sync_analyst_tracker_from_chunk(tracker, {}, now=10.0)
        self.assertEqual(tracker.get_wall_times(), {})

        sync_analyst_tracker_from_chunk(
            tracker,
            {"market_report": "done"},
            now=13.0,
        )
        self.assertEqual(tracker.get_wall_times(), {"market": 3.0})

        sync_analyst_tracker_from_chunk(
            tracker,
            {"market_report": "done", "news_report": "done"},
            now=18.0,
        )
        self.assertEqual(
            tracker.get_wall_times(),
            {"market": 3.0, "news": 8.0},
        )


class ParallelAnalystGraphTests(unittest.TestCase):
    def test_private_subgraph_returns_only_report_and_isolates_messages(self):
        spec = build_analyst_execution_plan(["market"]).specs[0]
        parent_message = HumanMessage(content="parent", id="parent-message")

        def analyst_node(state):
            return {
                "messages": [AIMessage(content="private", id="private-message")],
                "market_report": "market result",
                "sender": "Market Analyst",
            }

        wrapped = make_analyst_node(
            spec,
            lambda: analyst_node,
            lambda state: state,
            ConditionalLogic(),
        )
        state = {
            "messages": [parent_message],
            "company_of_interest": "NVDA",
            "asset_type": "stock",
            "instrument_context": "Ticker: NVDA",
            "trade_date": "2026-07-11",
        }

        result = wrapped(state, {})

        self.assertEqual(result, {"market_report": "market result"})
        self.assertEqual(state["messages"], [parent_message])

    def test_private_subgraph_propagates_analyst_failures(self):
        spec = build_analyst_execution_plan(["news"]).specs[0]

        def failing_analyst(_state):
            raise RuntimeError("news vendor failed")

        wrapped = make_analyst_node(
            spec,
            lambda: failing_analyst,
            lambda state: state,
            ConditionalLogic(),
        )

        with self.assertRaisesRegex(RuntimeError, "news vendor failed"):
            wrapped(
                {
                    "messages": [],
                    "company_of_interest": "NVDA",
                    "asset_type": "stock",
                    "instrument_context": "Ticker: NVDA",
                    "trade_date": "2026-07-11",
                },
                {},
            )

    @patch("tradingagents.graph.setup.create_portfolio_manager", return_value=lambda state: {})
    @patch("tradingagents.graph.setup.create_neutral_debator", return_value=lambda state: {})
    @patch("tradingagents.graph.setup.create_conservative_debator", return_value=lambda state: {})
    @patch("tradingagents.graph.setup.create_aggressive_debator", return_value=lambda state: {})
    @patch("tradingagents.graph.setup.create_trader", return_value=lambda state: {})
    @patch("tradingagents.graph.setup.create_research_manager", return_value=lambda state: {})
    @patch("tradingagents.graph.setup.create_bear_researcher", return_value=lambda state: {})
    @patch("tradingagents.graph.setup.create_bull_researcher", return_value=lambda state: {})
    def test_selected_analysts_fan_out_from_start_and_fan_in_to_research(
        self, *_mocks
    ):
        setup = GraphSetup(
            quick_thinking_llm=object(),
            deep_thinking_llm=object(),
            tool_nodes={"news": lambda state: state, "market": lambda state: state},
            conditional_logic=ConditionalLogic(),
        )

        with (
            patch("tradingagents.graph.setup.create_news_analyst", return_value=lambda state: {}),
            patch("tradingagents.graph.setup.create_market_analyst", return_value=lambda state: {}),
        ):
            workflow = setup.setup_graph(["news", "market"])

        self.assertIn((START, "News Analyst"), workflow.edges)
        self.assertIn((START, "Market Analyst"), workflow.edges)
        self.assertIn(("News Analyst", "Bull Researcher"), workflow.edges)
        self.assertIn(("Market Analyst", "Bull Researcher"), workflow.edges)
        self.assertNotIn(("News Analyst", "Market Analyst"), workflow.edges)
