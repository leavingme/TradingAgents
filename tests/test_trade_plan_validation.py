from unittest.mock import MagicMock

import pytest

from tradingagents.agents.schemas import (
    PortfolioDecision,
    PortfolioRating,
    TraderAction,
    TraderProposal,
    render_pm_decision,
    render_trader_proposal,
)
from tradingagents.agents.trade_plan import (
    TradePlanValidationError,
    validate_long_trade_plan,
)
from tradingagents.agents.utils.structured import invoke_structured_or_safe


@pytest.mark.unit
def test_trade_math_is_calculated_from_structured_numbers():
    metrics = validate_long_trade_plan(
        entry_price=214.0,
        stop_loss=200.0,
        price_target=224.0,
        atr=7.17,
        target_position_pct=4.0,
        initial_position_pct=1.4,
        max_portfolio_risk_pct=0.8,
    )
    assert metrics.reward_risk_ratio == pytest.approx(10 / 14)
    assert metrics.stop_atr_multiple == pytest.approx(14 / 7.17)
    assert metrics.initial_portfolio_risk_pct == pytest.approx(1.4 * 14 / 214)


@pytest.mark.unit
def test_inconsistent_long_price_order_is_a_hard_failure():
    with pytest.raises(TradePlanValidationError, match="stop_loss < entry_price < price_target"):
        validate_long_trade_plan(
            entry_price=210.0,
            stop_loss=220.0,
            price_target=200.0,
            atr=7.0,
            target_position_pct=4.0,
            initial_position_pct=1.5,
            max_portfolio_risk_pct=0.8,
        )


@pytest.mark.unit
def test_position_risk_above_limit_is_a_hard_failure():
    with pytest.raises(TradePlanValidationError, match="exceeds configured plan limit"):
        validate_long_trade_plan(
            entry_price=100.0,
            stop_loss=80.0,
            price_target=140.0,
            atr=5.0,
            target_position_pct=10.0,
            initial_position_pct=10.0,
            max_portfolio_risk_pct=1.0,
        )


@pytest.mark.unit
def test_pm_renderer_ignores_prose_arithmetic_and_emits_code_values():
    decision = PortfolioDecision(
        rating=PortfolioRating.OVERWEIGHT,
        executive_summary="Build gradually; arithmetic is rendered by code.",
        investment_thesis="Fundamentals support controlled exposure.",
        entry_price=214.0,
        stop_loss=200.0,
        price_target=224.0,
        atr=7.17,
        target_position_pct=4.0,
        initial_position_pct=1.4,
        max_portfolio_risk_pct=0.8,
    )
    rendered = render_pm_decision(decision)
    assert "**Reward/Risk (calculated)**: 0.71" in rendered
    assert "**Stop Distance (ATR, calculated)**: 1.95" in rendered
    assert "**Initial Portfolio Risk (calculated)**: 0.0916%" in rendered


@pytest.mark.unit
def test_incomplete_buy_is_retried_then_safely_downgraded():
    incomplete = TraderProposal(
        action=TraderAction.BUY,
        reasoning="Buy, but required risk fields are absent.",
        entry_price=210.0,
    )
    structured = MagicMock()
    structured.invoke.return_value = incomplete

    def safe(exc):
        assert isinstance(exc, TradePlanValidationError)
        return "HOLD REVIEW_REQUIRED"

    result = invoke_structured_or_safe(
        structured,
        "prompt",
        render_trader_proposal,
        safe,
        "Trader",
    )
    assert result == "HOLD REVIEW_REQUIRED"
    assert structured.invoke.call_count == 2
    second_prompt = structured.invoke.call_args_list[1].args[0]
    assert "missing structured fields" in second_prompt


@pytest.mark.unit
def test_unverified_trade_math_in_prose_is_rejected():
    with pytest.raises(ValueError, match="must not appear in prose"):
        PortfolioDecision(
            rating=PortfolioRating.HOLD,
            executive_summary="Claimed risk/reward is 1:3.",
            investment_thesis="Wait for confirmation.",
        )


@pytest.mark.unit
def test_executable_numbers_cannot_be_duplicated_in_prose():
    with pytest.raises(ValueError, match="must use structured fields"):
        PortfolioDecision(
            rating=PortfolioRating.HOLD,
            executive_summary="Start with a 40% position near $210.",
            investment_thesis="Wait for confirmation.",
        )


@pytest.mark.unit
def test_sell_cannot_bypass_direction_specific_numeric_validation():
    proposal = TraderProposal(
        action=TraderAction.SELL,
        reasoning="Exit the position.",
        entry_price=210.0,
        stop_loss=220.0,
    )
    with pytest.raises(TradePlanValidationError, match="non-long decision must omit"):
        render_trader_proposal(proposal)
