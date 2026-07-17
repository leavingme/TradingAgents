from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from tradingagents.agents.schemas import (
    PortfolioDecision,
    PortfolioRating,
    TraderAction,
    TraderProposal,
    contains_unverified_non_long_execution,
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
    assert "only in their dedicated structured fields" in second_prompt


@pytest.mark.unit
def test_non_long_trade_math_is_removed_without_turning_hold_into_no_decision():
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="Claimed risk/reward is 1:3. Maintain the qualitative view.",
        investment_thesis="Wait for confirmation.",
    )
    rendered = render_pm_decision(decision)
    assert "**Rating**: Hold" in rendered
    assert "risk/reward" not in rendered
    assert "Maintain the qualitative view" in rendered


@pytest.mark.unit
def test_non_long_executable_numbers_are_removed_from_prose():
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="Start with a 40% position near $210. Wait for confirmation.",
        investment_thesis="Evidence remains balanced.",
    )
    rendered = render_pm_decision(decision)
    assert "40%" not in rendered
    assert "$210" not in rendered
    assert "Wait for confirmation" in rendered


@pytest.mark.unit
def test_sanitized_numbered_list_does_not_leave_orphan_markers():
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="Wait for confirmation.",
        investment_thesis=(
            "1. Reduce position to 2% below $200. "
            "2. Fundamentals remain durable. "
            "3. Add a 1% hedge at strike $190."
        ),
    )
    rendered = render_pm_decision(decision)
    assert "Reduce position" not in rendered
    assert "hedge" not in rendered
    assert "1. 2." not in rendered
    assert "2. Fundamentals remain durable" in rendered


@pytest.mark.unit
def test_underweight_removes_reduce_rebuy_hedge_and_strike_numbers():
    decision = PortfolioDecision(
        rating=PortfolioRating.UNDERWEIGHT,
        executive_summary=(
            "跌破201美元减仓至25%，跌破192美元清仓。基本面仍有韧性。"
        ),
        investment_thesis=(
            "突破214美元回补至70%。买入Strike 200的Put对冲财报风险。"
            "短期赔率并不理想。"
        ),
    )
    rendered = render_pm_decision(decision)
    for forbidden in ("201", "25%", "192", "214", "70%", "Strike 200"):
        assert forbidden not in rendered
    assert "基本面仍有韧性" in rendered
    assert "短期赔率并不理想" in rendered


@pytest.mark.unit
def test_hold_removes_chinese_risk_reward_and_keeps_decimal_chunks_atomic():
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="当前风险/回报比为0.7:1。基本面仍有韧性。",
        investment_thesis=(
            "采纳触发方案：突破214.11美元后加仓至50%。"
            "等待方向明确后再行动。"
        ),
    )
    rendered = render_pm_decision(decision)
    for forbidden in ("风险/回报", "0.7:1", "214.11", "50%", "11美元"):
        assert forbidden not in rendered
    assert "基本面仍有韧性" in rendered
    assert "等待方向明确后再行动" in rendered


@pytest.mark.parametrize("phrase", ["风险收益比 1:3", "风险回报比为 1:2"])
def test_hold_removes_chinese_risk_reward_synonyms(phrase):
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="维持观察。",
        investment_thesis=f"当前{phrase}。等待财报确认。",
    )
    rendered = render_pm_decision(decision)
    assert phrase not in rendered
    assert "等待财报确认" in rendered


def test_hold_removes_numeric_odds_ratio_even_when_quoted_as_criticism():
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="维持观察。",
        investment_thesis="激进派把赔率 1:3 包装成确定性机会。证据仍然平衡。",
    )
    rendered = render_pm_decision(decision)
    assert "1:3" not in rendered
    assert "证据仍然平衡" in rendered


def test_hold_removes_conditional_actions_using_chinese_numerals():
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="维持观察。",
        investment_thesis=(
            "可执行纪律：三正加仓、两正一平维持、两负减仓。"
            "等待财报确认。"
        ),
    )
    rendered = render_pm_decision(decision)
    assert "三正加仓" not in rendered
    assert "两负减仓" not in rendered
    assert "等待财报确认" in rendered


@pytest.mark.unit
def test_hold_removes_target_level_synonym_from_prose():
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="维持观察。",
        investment_thesis="第一目标位 220-225 美元。基本面质量仍然很高。",
    )
    rendered = render_pm_decision(decision)
    assert "220-225" not in rendered
    assert "目标位" not in rendered
    assert "基本面质量仍然很高" in rendered


@pytest.mark.unit
def test_underweight_removes_chinese_atr_multiple():
    decision = PortfolioDecision(
        rating=PortfolioRating.UNDERWEIGHT,
        executive_summary="等待财报后重新评估。",
        investment_thesis="估值与1.5倍ATR波动率叠加。长期护城河仍然存在。",
    )
    rendered = render_pm_decision(decision)
    assert "1.5倍ATR" not in rendered
    assert "长期护城河仍然存在" in rendered


@pytest.mark.unit
def test_hold_removes_tactical_position_reduction_synonym():
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="维持观察。",
        investment_thesis=(
            "30-60天内若政策无落地，主动降低战术仓10-15%。"
            "等待官方政策确认。"
        ),
    )
    rendered = render_pm_decision(decision)
    assert "10-15%" not in rendered
    assert "降低战术仓" not in rendered
    assert "等待官方政策确认" in rendered


@pytest.mark.unit
def test_negative_sell_rating_context_is_not_an_execution_false_positive():
    report = "多方证据确认（不支持Sell的论据）：FY27 Q1营收$81.6B。"
    assert not contains_unverified_non_long_execution(report)


@pytest.mark.unit
def test_hold_with_triggers_heading_and_calendar_number_is_not_execution():
    report = "最终决策：Hold with Triggers。关键观察点：Q2 财报在 8 月发布。"
    assert not contains_unverified_non_long_execution(report)


def test_negative_sell_heading_list_number_is_not_execution():
    report = "**为何Sell/Underweight不成立**： 1. 下行有$40B净现金支撑。"
    assert not contains_unverified_non_long_execution(report)


def test_why_not_reduce_heading_is_not_execution_false_positive():
    report = (
        "### 为什么不是减仓/Underweight "
        "保守派关于71.5%净利率不可持续的论证属于长期风险。"
    )
    assert not contains_unverified_non_long_execution(report)


def test_why_not_reduce_heading_does_not_hide_real_reduction_instruction():
    report = (
        "### 为什么不是减仓/Underweight "
        "长期基本面仍稳健；跌破$200后减仓20%。"
    )
    assert contains_unverified_non_long_execution(report)


@pytest.mark.parametrize(
    "heading",
    ["支撑 Hold（不卖出）的硬证据", "支撑 Hold（不加仓）的硬证据"],
)
def test_hold_negative_action_heading_is_not_execution(heading):
    assert not contains_unverified_non_long_execution(
        f"**{heading}**： 1. 趋势仍待确认。"
    )


def test_hold_negative_heading_does_not_hide_real_conditional_action():
    report = "**支撑 Hold（不加仓）的硬证据**：跌破$200后卖出。"
    assert contains_unverified_non_long_execution(report)


def test_why_not_add_heading_does_not_turn_indicator_distance_into_execution():
    report = "**为何不做方向性加仓** 当前价格距布林上轨仅约1.5%。"
    assert not contains_unverified_non_long_execution(report)


def test_why_not_add_heading_does_not_hide_following_real_action():
    report = "**为何不做方向性加仓** 当前距上轨1.5%，突破后加仓20%。"
    assert contains_unverified_non_long_execution(report)


def test_trigger_heading_with_month_end_and_quarter_is_not_execution():
    report = "**触发框架（纪律性动作边界）**： - **8月底Q2财报结果**"
    assert not contains_unverified_non_long_execution(report)


def test_calendar_normalization_does_not_hide_real_execution_trigger():
    report = "8月底Q2财报后，trigger at $200 and reduce exposure."
    assert contains_unverified_non_long_execution(report)


@pytest.mark.unit
def test_pm_rejects_currency_unit_drift_from_chinese_billions():
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="等待财报确认。",
        investment_thesis="若营收达到$910B则重新评估。",
    )
    with pytest.raises(ValueError, match="not supported by upstream evidence"):
        render_pm_decision(decision, evidence_context="公司指引为$910亿。")


@pytest.mark.unit
def test_pm_accepts_equivalent_currency_units_and_rounding():
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="等待财报确认。",
        investment_thesis="净利润约$58.3B，净现金约$40B。",
    )
    rendered = render_pm_decision(
        decision,
        evidence_context="净利润$583亿，净现金$403亿。",
    )
    assert "$58.3B" in rendered
    assert "$40B" in rendered


@pytest.mark.unit
def test_pm_rejects_unsupported_currency_range_after_unit_conversion():
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="等待财报确认。",
        investment_thesis="报告引用的营收区间为$880-900B。",
    )
    with pytest.raises(ValueError, match=r"\$880-900B"):
        render_pm_decision(decision, evidence_context="营收预期为$880到900亿。")


@pytest.mark.unit
def test_pm_rejects_unsupported_bare_chinese_currency_range():
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="等待财报确认。",
        investment_thesis="下一季度营收预计为540-570亿美元。",
    )
    with pytest.raises(ValueError, match="540-570亿"):
        render_pm_decision(decision, evidence_context="管理层指引为$910亿。")


@pytest.mark.unit
def test_pm_validates_chinese_usd_suffix_and_range_against_evidence():
    supported = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="当前价格211.80美元。",
        investment_thesis="压力情景为160甚至152美元。",
    )
    rendered = render_pm_decision(
        supported,
        evidence_context="收盘价211.80美元，情景水平为160美元与152美元。",
    )
    assert "160甚至152美元" in rendered

    unsupported = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="维持观察。",
        investment_thesis="等待可能错失20美元。",
    )
    with pytest.raises(ValueError, match="20美元"):
        render_pm_decision(unsupported, evidence_context="收盘价211.80美元。")


@pytest.mark.unit
def test_explicit_trigger_price_remains_executable_guidance():
    report = "Hold, but trigger at $200 and reduce exposure."
    assert contains_unverified_non_long_execution(report)


@pytest.mark.unit
def test_long_executable_math_in_prose_remains_a_hard_failure():
    decision = PortfolioDecision(
        rating=PortfolioRating.BUY,
        executive_summary="Start with a 4% position near $210.",
        investment_thesis="Fundamentals support the long.",
        entry_price=210, stop_loss=200, price_target=230,
        target_position_pct=4, initial_position_pct=1,
    )
    with pytest.raises(ValueError, match="must use structured fields"):
        render_pm_decision(decision, verified_market=VERIFIED, risk_policy=POLICY)


@pytest.mark.unit
def test_trader_hold_sanitizes_copied_executable_plan_sentences():
    proposal = TraderProposal(
        action=TraderAction.HOLD,
        reasoning="Do not add at a $210 entry. Evidence remains balanced.",
    )
    rendered = render_trader_proposal(proposal)
    assert "**Action**: Hold" in rendered
    assert "$210" not in rendered
    assert "Evidence remains balanced" in rendered


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
