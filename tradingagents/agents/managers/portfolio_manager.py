"""Portfolio Manager: synthesises the risk-analyst debate into the final decision.

Uses LangChain's ``with_structured_output`` so the LLM produces a typed
``PortfolioDecision`` directly, in a single call.  The result is rendered
back to markdown for storage in ``final_trade_decision`` so memory log,
CLI display, and saved reports continue to consume the same shape they do
today.  When a provider does not expose structured output, the agent falls
back gracefully to free-text generation.
"""

from __future__ import annotations

from tradingagents.agents.schemas import (
    PortfolioDecision,
    render_pm_decision,
    render_review_required,
)
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_safe,
)


def create_portfolio_manager(llm):
    structured_llm = bind_structured(llm, PortfolioDecision, "Portfolio Manager")

    def portfolio_manager_node(state) -> dict:
        instrument_context = get_instrument_context_from_state(state)

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]
        verified_market = state["verified_market_snapshot"]
        risk_policy = state["trade_risk_policy"]
        analyst_evidence = "\n".join(
            str(state.get(key) or "")
            for key in (
                "market_report",
                "sentiment_report",
                "news_report",
                "fundamentals_report",
            )
        )

        past_context = state.get("past_context", "")
        lessons_line = (
            f"- Lessons from prior decisions and outcomes:\n{past_context}\n"
            if past_context
            else ""
        )

        if "REVIEW_REQUIRED" in trader_plan:
            final_trade_decision = render_review_required(
                stage="Trader",
                reason=(
                    "The executable proposal did not pass deterministic validation; "
                    "the downstream risk debate cannot authorize it."
                ),
            )
            new_risk_debate_state = {
                **risk_debate_state,
                "judge_decision": final_trade_decision,
                "latest_speaker": "Judge",
            }
            return {
                "risk_debate_state": new_risk_debate_state,
                "final_trade_decision": final_trade_decision,
                "decision_status": "review_required",
            }

        prompt = f"""As the Portfolio Manager, synthesize the risk analysts' debate and deliver the final trading decision.

{instrument_context}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction to enter or add to position
- **Overweight**: Favorable outlook, gradually increase exposure
- **Hold**: Maintain current position, no action needed
- **Underweight**: Reduce exposure, take partial profits
- **Sell**: Exit position or avoid entry

**Context:**
- Research Manager's investment plan: **{research_plan}**
- Trader's transaction proposal: **{trader_plan}**
{lessons_line}
**Risk Analysts Debate History:**
{history}

---

Be decisive and ground every conclusion in specific evidence from the analysts.{get_language_instruction()}"""

        prompt += """

For Buy or Overweight, all executable numbers MUST be supplied through the
structured fields: entry_price, stop_loss, price_target,
target_position_pct, and initial_position_pct.
Do not calculate or state reward/risk, ATR multiples, or portfolio-loss math in
prose. Do not repeat executable entry, stop, target, ATR, or position numbers in
prose; deterministic code will render the structured fields. If reliable
numeric inputs are unavailable, choose Hold rather than inventing them.
For Hold, Underweight, or Sell, omit all executable numeric fields; those
directions do not yet have an approved direction-specific calculator."""

        def safe_pm_decision(exc: Exception) -> str:
            return render_review_required(
                stage="Portfolio Manager",
                reason=f"Validation failure: {type(exc).__name__}: {exc}",
            )

        final_trade_decision = invoke_structured_or_safe(
            structured_llm,
            prompt,
            lambda decision: render_pm_decision(
                decision,
                verified_market=verified_market,
                risk_policy=risk_policy,
                evidence_context=analyst_evidence,
            ),
            safe_pm_decision,
            "Portfolio Manager",
        )
        decision_status = (
            "review_required" if "REVIEW_REQUIRED" in final_trade_decision else "validated"
        )

        new_risk_debate_state = {
            "judge_decision": final_trade_decision,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_trade_decision,
            "decision_status": decision_status,
        }

    return portfolio_manager_node
