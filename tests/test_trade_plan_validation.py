from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

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

VERIFIED = {
    "market_date": "2026-07-10", "close": 210.96, "atr": 7.17,
    "vendor_call_id": "call-verified",
}
POLICY = {
    "max_portfolio_risk_pct": 0.8,
    "max_position_pct": 5.0,
    "max_notional_exposure_pct": 5.0,
    "available_buying_power_pct": 100.0,
    "allow_new_long_positions": True,
    "max_entry_deviation_pct": 20.0,
}


@pytest.mark.unit
def test_trade_math_is_calculated_from_structured_numbers():
    metrics = validate_long_trade_plan(
        entry_price=214.0,
        stop_loss=200.0,
        price_target=224.0,
        target_position_pct=4.0,
        initial_position_pct=1.4,
        verified_close=VERIFIED["close"], verified_atr=VERIFIED["atr"],
        **POLICY,
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
            target_position_pct=4.0,
            initial_position_pct=1.5,
            verified_close=210.0, verified_atr=7.0, **POLICY,
        )


@pytest.mark.unit
def test_position_risk_above_limit_is_a_hard_failure():
    with pytest.raises(TradePlanValidationError, match="exceeds configured plan limit"):
        validate_long_trade_plan(
            entry_price=100.0,
            stop_loss=80.0,
            price_target=140.0,
            target_position_pct=5.0,
            initial_position_pct=5.0,
            verified_close=100.0, verified_atr=5.0,
            max_portfolio_risk_pct=0.5,
            max_position_pct=5.0, max_entry_deviation_pct=20.0,
            max_notional_exposure_pct=5.0,
            available_buying_power_pct=100.0,
            allow_new_long_positions=True,
        )


@pytest.mark.unit
def test_entry_far_from_verified_close_is_a_hard_failure():
    with pytest.raises(TradePlanValidationError, match="verified Close"):
        validate_long_trade_plan(
            entry_price=130.0,
            stop_loss=120.0,
            price_target=150.0,
            target_position_pct=4.0,
            initial_position_pct=1.0,
            verified_close=100.0,
            verified_atr=5.0,
            **POLICY,
        )


@pytest.mark.unit
def test_position_above_server_limit_is_a_hard_failure():
    with pytest.raises(TradePlanValidationError, match="target_position_pct"):
        validate_long_trade_plan(
            entry_price=100.0,
            stop_loss=95.0,
            price_target=115.0,
            target_position_pct=5.1,
            initial_position_pct=1.0,
            verified_close=100.0,
            verified_atr=5.0,
            **POLICY,
        )


@pytest.mark.unit
def test_llm_cannot_supply_authoritative_atr_or_risk_limit():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        TraderProposal(
            action=TraderAction.BUY,
            reasoning="Validated inputs must come from the server.",
            atr=0.01,
        )


@pytest.mark.unit
def test_server_account_policy_can_block_new_long_or_limit_buying_power():
    blocked = dict(POLICY, allow_new_long_positions=False)
    with pytest.raises(TradePlanValidationError, match="does not allow"):
        validate_long_trade_plan(
            entry_price=100, stop_loss=95, price_target=115,
            target_position_pct=2, initial_position_pct=1,
            verified_close=100, verified_atr=5, **blocked,
        )
    constrained = dict(POLICY, available_buying_power_pct=1.5)
    with pytest.raises(TradePlanValidationError, match="effective server/account limit"):
        validate_long_trade_plan(
            entry_price=100, stop_loss=95, price_target=115,
            target_position_pct=2, initial_position_pct=1,
            verified_close=100, verified_atr=5, **constrained,
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PortfolioDecision(
            rating=PortfolioRating.HOLD,
            executive_summary="Wait.",
            investment_thesis="No edge.",
            max_portfolio_risk_pct=99.0,
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
        target_position_pct=4.0,
        initial_position_pct=1.4,
    )
    rendered = render_pm_decision(decision, verified_market=VERIFIED, risk_policy=POLICY)
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
        lambda proposal: render_trader_proposal(
            proposal, verified_market=VERIFIED, risk_policy=POLICY
        ),
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
