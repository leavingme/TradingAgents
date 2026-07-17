"""Trader: turns the Research Manager's investment plan into a concrete transaction proposal."""

from __future__ import annotations

import functools

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import (
    TraderProposal,
    render_review_required,
    render_trader_proposal,
)
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_safe,
)


def create_trader(llm):
    structured_llm = bind_structured(llm, TraderProposal, "Trader")

    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = get_instrument_context_from_state(state)
        investment_plan = state["investment_plan"]
        verified_market = state["verified_market_snapshot"]
        risk_policy = state["trade_risk_policy"]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a trading agent analyzing market data to make investment decisions. "
                    "Based on your analysis, provide a specific recommendation to buy, sell, or hold. "
                    "Anchor your reasoning in the analysts' reports and the research plan."
                    " For Buy, provide every structured risk field; deterministic code calculates "
                    "derived metrics. Copy no executable price, trigger, ATR, reward/risk, option, "
                    "hedge, or position-size number into reasoning, even when the research plan "
                    "contains one; transfer only the selected entry, stop, target, and position "
                    "values into their dedicated structured fields. For Hold or Sell, omit all "
                    "executable numeric fields and keep the reasoning qualitative."
                    + get_language_instruction()
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Based on a comprehensive analysis by a team of analysts, here is an investment "
                    f"plan tailored for {company_name}. {instrument_context} This plan incorporates "
                    f"insights from current technical market trends, macroeconomic indicators, and "
                    f"social media sentiment. Use this plan as a foundation for evaluating your next "
                    f"trading decision.\n\nProposed Investment Plan: {investment_plan}\n\n"
                    f"Treat the plan as non-authoritative research context. Do not copy any of its "
                    f"execution numbers into prose. Only dedicated structured fields can authorize "
                    f"a price or position value."
                ),
            },
        ]

        def safe_trader_plan(exc: Exception) -> str:
            return render_review_required(
                stage="Trader",
                reason=f"Validation failure: {type(exc).__name__}: {exc}",
            )

        trader_plan = invoke_structured_or_safe(
            structured_llm,
            messages,
            lambda proposal: render_trader_proposal(
                proposal,
                verified_market=verified_market,
                risk_policy=risk_policy,
            ),
            safe_trader_plan,
            "Trader",
        )

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
