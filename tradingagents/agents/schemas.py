"""Pydantic schemas used by agents that produce structured output.

The framework's primary artifact is still prose: each agent's natural-language
reasoning is what users read in the saved markdown reports and what the
downstream agents read as context.  Structured output is layered onto the
three decision-making agents (Research Manager, Trader, Portfolio Manager)
so that:

- Their outputs follow consistent section headers across runs and providers
- Each provider's native structured-output mode is used (json_schema for
  OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic)
- Schema field descriptions become the model's output instructions, freeing
  the prompt body to focus on context and the rating-scale guidance
- A render helper turns the parsed Pydantic instance back into the same
  markdown shape the rest of the system already consumes, so display,
  memory log, and saved reports keep working unchanged
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
import re

# LLMs sometimes write a placeholder string ("None", "N/A", ...) into an optional
# numeric field instead of omitting it. Coerce those to None so the structured
# call validates instead of erroring (#1058). Pydantic still parses real numeric
# strings ("189.5") to float.
_NULLISH_FLOAT = {"", "none", "n/a", "na", "null", "nil", "-", "tbd", "unknown"}


def _coerce_optional_float(value):
    if isinstance(value, str) and value.strip().lower() in _NULLISH_FLOAT:
        return None
    return value


_PROSE_TRADE_MATH = re.compile(
    r"risk\s*[/:-]?\s*reward|reward\s*[/:-]?\s*risk|"
    r"风险\s*[/：:]?\s*回报|风险\s*(?:收益|回报)\s*比|盈亏比|"
    r"赔率\s*\d+(?:\.\d+)?\s*[:：比]\s*\d+(?:\.\d+)?|"
    r"\d+(?:\.\d+)?\s*(?:[×x]|倍)\s*atr|atr\s*(?:倍数|multiple)|"
    r"initial portfolio risk|初始组合风险",
    re.IGNORECASE,
)
_PROSE_EXECUTABLE_NUMBER = re.compile(
    r"(?:entry|stop(?:[- ]loss)?|price target|position(?:\s+siz(?:e|ing))?|"
    r"cap(?:ped)?(?:\s+(?:at|to))?|"
    r"reduce|trim|exit|(?<!not )(?<!不支持)(?<!不是)sell|buyback|hedge|strike|exposure|"
    r"trigger(?:ed|s)?\s+(?:at|above|below|price|level)|break(?:s)? (?:above|below)|"
    r"入场|止损|目标价|目标位|仓位|持仓|战术仓|建仓|加仓|减仓|减持|清仓|回补|"
    r"(?:降低|提高|调整|削减|保留)[^\n.!?。！？]{0,8}(?:仓|敞口)|"
    r"卖出|买入|对冲|行权价|敞口|触发|跌破|突破)"
    r"[^\n.!?。！？]{0,35}(?:\$?\d+(?:\.\d+)?%?)|"
    r"(?:\$?\d+(?:\.\d+)?%?)[^\n.!?。！？]{0,20}"
    r"(?:entry|stop(?:[- ]loss)?|price target|position|reduce|trim|exit|(?<!not )(?<!不支持)(?<!不是)sell|buyback|"
    r"hedge|strike|exposure|trigger(?:ed|s)?\s+(?:at|above|below|price|level)|"
    r"break(?:s)? (?:above|below)|"
    r"入场|止损|目标价|目标位|仓位|持仓|战术仓|建仓|加仓|减仓|减持|清仓|回补|"
    r"(?:降低|提高|调整|削减|保留)[^\n.!?。！？]{0,8}(?:仓|敞口)|"
    r"卖出|买入|对冲|行权价|敞口|触发|跌破|突破)",
    re.IGNORECASE,
)
_PROSE_EXECUTABLE_CHINESE_NUMBER = re.compile(
    r"(?:入场|止损|目标价|目标位|仓位|持仓|战术仓|建仓|加仓|减仓|减持|"
    r"清仓|回补|卖出|买入|对冲|行权价|敞口|触发|跌破|突破)"
    r"[^\n.!?。！？]{0,20}[一二两三四五六七八九十百]+|"
    r"[一二两三四五六七八九十百]+[^\n.!?。！？]{0,10}"
    r"(?:入场|止损|目标价|目标位|仓位|持仓|战术仓|建仓|加仓|减仓|减持|"
    r"清仓|回补|卖出|买入|对冲|行权价|敞口|触发|跌破|突破)",
    re.IGNORECASE,
)

_CURRENCY_RANGE = re.compile(
    r"\$\s*(\d+(?:\.\d+)?)\s*[-–—至到]\s*\$?\s*(\d+(?:\.\d+)?)"
    r"\s*(万亿|亿|[TtBbMm])"
)
_CHINESE_LARGE_RANGE = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*[-–—至到]\s*(\d+(?:\.\d+)?)"
    r"\s*(万亿|亿)"
)
_USD_SUFFIX_RANGE = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:[-–—至到]|甚至)\s*"
    r"(\d+(?:\.\d+)?)\s*美元"
)
_CURRENCY_SCALAR = re.compile(
    r"\$\s*(\d+(?:\.\d+)?)\s*(万亿|亿|[TtBbMm])?"
)
_CHINESE_LARGE_NUMBER = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(万亿|亿)")
_USD_SUFFIX_SCALAR = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*美元")


def _currency_values(value: str) -> list[tuple[str, float]]:
    """Extract dollar amounts and normalize them to absolute USD values."""
    extracted: list[tuple[str, float]] = []
    range_spans: list[tuple[int, int]] = []

    def normalize(number: str, unit: str | None) -> float:
        multipliers = {
            None: 1.0,
            "M": 1_000_000.0,
            "B": 1_000_000_000.0,
            "T": 1_000_000_000_000.0,
            "亿": 100_000_000.0,
            "万亿": 1_000_000_000_000.0,
        }
        normalized_unit = unit.upper() if unit and unit.isascii() else unit
        return float(number) * multipliers[normalized_unit]

    for match in _CURRENCY_RANGE.finditer(value):
        range_spans.append(match.span())
        for number in match.group(1), match.group(2):
            extracted.append((match.group(0), normalize(number, match.group(3))))
    for match in _CHINESE_LARGE_RANGE.finditer(value):
        range_spans.append(match.span())
        for number in match.group(1), match.group(2):
            extracted.append((match.group(0), normalize(number, match.group(3))))
    for match in _USD_SUFFIX_RANGE.finditer(value):
        range_spans.append(match.span())
        for number in match.group(1), match.group(2):
            extracted.append((match.group(0), normalize(number, None)))
    for match in _CURRENCY_SCALAR.finditer(value):
        if any(start <= match.start() < end for start, end in range_spans):
            continue
        extracted.append((match.group(0), normalize(match.group(1), match.group(2))))
    occupied = [*range_spans, *(match.span() for match in _CURRENCY_SCALAR.finditer(value))]
    for match in _CHINESE_LARGE_NUMBER.finditer(value):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        extracted.append((match.group(0), normalize(match.group(1), match.group(2))))
    for match in _USD_SUFFIX_SCALAR.finditer(value):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        extracted.append((match.group(0), normalize(match.group(1), None)))
    return extracted


def unsupported_currency_amounts(value: str, evidence_context: str) -> list[str]:
    """Return output dollar amounts that cannot be reconciled to upstream evidence.

    Chinese ``亿``/``万亿`` and English M/B/T suffixes are normalized before
    comparison. This catches silent 10x/100x unit drift during multilingual
    hand-offs while allowing ordinary rounding (up to one percent).
    """
    evidence_values = [amount for _, amount in _currency_values(evidence_context)]
    unsupported: list[str] = []
    for rendered, amount in _currency_values(value):
        if not any(
            abs(amount - evidence) <= max(0.05, abs(evidence) * 0.01)
            for evidence in evidence_values
        ):
            unsupported.append(rendered)
    return list(dict.fromkeys(unsupported))


def _validate_currency_evidence(value: str, evidence_context: str | None) -> str:
    if not evidence_context:
        return value
    unsupported = unsupported_currency_amounts(value, evidence_context)
    if unsupported:
        raise ValueError(
            "currency amounts are not supported by upstream evidence after unit "
            f"normalization: {', '.join(unsupported)}"
        )
    return value


def _execution_scan_text(value: str) -> str:
    """Remove non-executable numbering before scanning prose for trade levels."""
    # A section explicitly explaining why Sell/Underweight is not justified is
    # rating analysis, not a sell instruction. Remove only that negated heading;
    # genuine Sell prose and all following financial numbers remain scannable.
    value = re.sub(
        r"(?i)为何\s*sell(?:\s*/\s*underweight)?\s*不成立",
        "反对非多头评级",
        value,
    )
    value = re.sub(
        r"(?i)(?:为何|为什么)\s*不是\s*"
        r"(?:减仓|减持|卖出|清仓|sell|underweight)"
        r"(?:\s*/\s*(?:减仓|减持|卖出|清仓|sell|underweight))?",
        "反对非多头评级",
        value,
    )
    value = re.sub(
        r"(?i)为何\s*不做\s*方向性\s*(?:加仓|减仓)",
        "维持当前方向的理由",
        value,
    )
    value = re.sub(
        r"(?i)支撑\s*hold\s*[（(]\s*不(?:卖出|加仓)\s*[）)](?:的)?硬证据",
        "支撑维持评级的硬证据",
        value,
    )
    # Markdown/natural-language ordered-list markers are not prices. Require a
    # dot followed by whitespace/markdown so decimal values remain intact.
    value = re.sub(r"(?<![\d.])\d+\.(?=\s|\*\*)", "", value)
    # Calendar references such as Q2 and 8月底 are catalysts, not execution
    # numbers. Actual dollar/percent/ATR/position values remain untouched.
    value = re.sub(r"(?i)(?<![A-Z0-9])Q[1-4](?![0-9])", "", value)
    value = re.sub(
        r"(?<![\d.])(?:1[0-2]|[1-9])\s*月(?:底|初|中旬|下旬)?",
        "",
        value,
    )
    return value


def _reject_calculated_trade_math(value: str) -> str:
    scan_text = _execution_scan_text(value)
    if _PROSE_TRADE_MATH.search(scan_text):
        raise ValueError(
            "calculated reward/risk, ATR multiples, and portfolio risk must not appear in prose"
        )
    if _PROSE_EXECUTABLE_NUMBER.search(scan_text):
        raise ValueError(
            "executable entry, stop, target, and position numbers must use structured fields, not prose"
        )
    if _PROSE_EXECUTABLE_CHINESE_NUMBER.search(scan_text):
        raise ValueError(
            "executable entry, stop, target, and position numbers must use structured fields, not prose"
        )
    return value


def _sanitize_non_executable_prose(value: str) -> str:
    """Remove executable-number sentences from non-authoritative prose.

    Research plans and non-long ratings may retain qualitative conclusions,
    but copied entry/stop/target/position math must not survive into the next
    decision boundary. Long decisions stay strict and fail instead of being
    silently rewritten because their structured fields are executable.
    """
    # Keep ordered-list markers attached to their item while splitting prose.
    # Otherwise removing an unsafe item leaves orphaned ``1. 2. 3.`` markers
    # in the rendered report.
    list_dot = "__TRADINGAGENTS_LIST_DOT__"
    value = re.sub(
        r"(?<!\S)(\d{1,2})\.(?=\s)",
        rf"\1{list_dot}",
        value,
    )
    # An ASCII dot is a sentence boundary only before whitespace/end. This
    # preserves decimal values (214.11) inside the unsafe chunk so the whole
    # guidance is removed instead of leaking fragments such as "11 + ...".
    chunks = re.split(r"(?<=[!?。！？;；])|(?<=\.)(?=\s|$)|\n+", value)
    safe = [
        chunk.strip()
        for chunk in chunks
        if chunk.strip()
        and not _PROSE_TRADE_MATH.search(_execution_scan_text(chunk))
        and not _PROSE_EXECUTABLE_NUMBER.search(_execution_scan_text(chunk))
        and not _PROSE_EXECUTABLE_CHINESE_NUMBER.search(_execution_scan_text(chunk))
    ]
    if safe:
        return " ".join(safe).replace(list_dot, ".")
    return "Executable numeric guidance was removed; no transaction is authorized."


def contains_unverified_non_long_execution(value: str) -> bool:
    """Return whether non-long prose still carries executable numeric guidance."""
    scan_text = _execution_scan_text(value)
    return bool(
        _PROSE_TRADE_MATH.search(scan_text)
        or _PROSE_EXECUTABLE_NUMBER.search(scan_text)
        or _PROSE_EXECUTABLE_CHINESE_NUMBER.search(scan_text)
    )


# ---------------------------------------------------------------------------
# Shared rating types
# ---------------------------------------------------------------------------


class PortfolioRating(str, Enum):
    """5-tier rating used by the Research Manager and Portfolio Manager."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    """3-tier transaction direction used by the Trader.

    The Trader's job is to translate the Research Manager's investment plan
    into a concrete transaction proposal: should the desk execute a Buy, a
    Sell, or sit on Hold this round.  Position sizing and the nuanced
    Overweight / Underweight calls happen later at the Portfolio Manager.
    """

    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


# ---------------------------------------------------------------------------
# Research Manager
# ---------------------------------------------------------------------------


class ResearchPlan(BaseModel):
    """Structured investment plan produced by the Research Manager.

    Hand-off to the Trader: the recommendation pins the directional view,
    the rationale captures which side of the bull/bear debate carried the
    argument, and the strategic actions translate that into concrete
    instructions the trader can execute against.
    """

    model_config = ConfigDict(extra="forbid")

    recommendation: PortfolioRating = Field(
        description=(
            "The investment recommendation. Exactly one of Buy / Overweight / "
            "Hold / Underweight / Sell. Reserve Hold for situations where the "
            "evidence on both sides is genuinely balanced; otherwise commit to "
            "the side with the stronger arguments."
        ),
    )
    rationale: str = Field(
        description=(
            "Conversational summary of the key points from both sides of the "
            "debate, ending with which arguments led to the recommendation. "
            "Speak naturally, as if to a teammate."
        ),
    )
    strategic_actions: str = Field(
        description=(
            "Qualitative strategy directions for the trader. Do not include "
            "executable entry, stop, target, trigger, option strike, hedge, or "
            "position-size numbers; those belong only in the Trader's validated "
            "structured fields."
        ),
    )


def render_research_plan(plan: ResearchPlan) -> str:
    """Render a non-authoritative plan for storage and the trader prompt.

    The Research Manager has no server risk policy or direction-specific trade
    validator. Strip any copied execution levels before this prose crosses the
    executable Trader boundary; ordinary financial evidence remains intact.
    """
    rationale = _sanitize_non_executable_prose(plan.rationale)
    strategic_actions = _sanitize_non_executable_prose(plan.strategic_actions)
    return "\n".join([
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {rationale}",
        "",
        f"**Strategic Actions**: {strategic_actions}",
    ])


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------


class TraderProposal(BaseModel):
    """Structured transaction proposal produced by the Trader.

    The trader reads the Research Manager's investment plan and the analyst
    reports, then turns them into a concrete transaction: what action to
    take, the reasoning that justifies it, and the practical levels for
    entry, stop-loss, and sizing.
    """

    model_config = ConfigDict(extra="forbid")

    action: TraderAction = Field(
        description="The transaction direction. Exactly one of Buy / Hold / Sell.",
    )
    reasoning: str = Field(
        description=(
            "The case for this action, anchored in the analysts' reports and "
            "the research plan. Two to four sentences. Keep this field "
            "qualitative: do not repeat executable entry, stop, target, trigger, "
            "ATR, reward/risk, or position-size numbers here. For Buy, put the "
            "chosen executable values only in their dedicated numeric fields. "
            "To make this separation deterministic, use no digits, currency "
            "symbols, percent signs, Chinese numeric characters, or ATR token "
            "anywhere in reasoning; describe evidence directionally instead."
        ),
    )
    entry_price: float | None = Field(
        default=None,
        description="Optional entry price target in the instrument's quote currency.",
    )
    stop_loss: float | None = Field(
        default=None,
        description="Optional stop-loss price in the instrument's quote currency.",
    )
    price_target: float | None = Field(
        default=None,
        description="Required target price for Buy proposals.",
    )
    target_position_pct: float | None = Field(
        default=None,
        description="Required final target position as percent of portfolio for Buy proposals.",
    )
    initial_position_pct: float | None = Field(
        default=None,
        description="Required initial position as percent of portfolio for Buy proposals.",
    )
    @field_validator(
        "entry_price", "stop_loss", "price_target",
        "target_position_pct", "initial_position_pct",
        mode="before",
    )
    @classmethod
    def _nullish_float_to_none(cls, v):
        return _coerce_optional_float(v)

def render_trader_proposal(
    proposal: TraderProposal,
    *,
    verified_market: dict | None = None,
    risk_policy: dict | None = None,
) -> str:
    """Render a TraderProposal to markdown.

    The trailing ``FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`` line is
    preserved for backward compatibility with the analyst stop-signal text
    and any external code that greps for it.
    """
    metrics = None
    reasoning = proposal.reasoning
    if proposal.action is TraderAction.BUY:
        from .trade_plan import validate_long_trade_plan

        if not verified_market or not risk_policy:
            raise ValueError("trusted market snapshot and server risk policy are required")

        reasoning = _reject_calculated_trade_math(reasoning)

        metrics = validate_long_trade_plan(
            entry_price=proposal.entry_price,
            stop_loss=proposal.stop_loss,
            price_target=proposal.price_target,
            target_position_pct=proposal.target_position_pct,
            initial_position_pct=proposal.initial_position_pct,
            verified_close=verified_market["close"],
            verified_atr=verified_market["atr"],
            max_portfolio_risk_pct=risk_policy["max_portfolio_risk_pct"],
            max_position_pct=risk_policy["max_position_pct"],
            max_notional_exposure_pct=risk_policy["max_notional_exposure_pct"],
            available_buying_power_pct=risk_policy["available_buying_power_pct"],
            allow_new_long_positions=risk_policy["allow_new_long_positions"],
            max_entry_deviation_pct=risk_policy["max_entry_deviation_pct"],
        )
    else:
        from .trade_plan import reject_numeric_plan_fields

        reject_numeric_plan_fields(
            entry_price=proposal.entry_price,
            stop_loss=proposal.stop_loss,
            price_target=proposal.price_target,
            target_position_pct=proposal.target_position_pct,
            initial_position_pct=proposal.initial_position_pct,
        )
        reasoning = _sanitize_non_executable_prose(reasoning)
    parts = [
        f"**Action**: {proposal.action.value}",
        "",
        f"**Reasoning**: {reasoning}",
    ]
    if proposal.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {proposal.entry_price}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {proposal.stop_loss}"])
    if proposal.price_target is not None:
        parts.extend(["", f"**Price Target**: {proposal.price_target}"])
    if metrics is not None:
        parts.extend([
            "",
            f"**Reward/Risk (calculated)**: {metrics.reward_risk_ratio:.2f}",
            "",
            f"**Stop Distance (ATR, calculated)**: {metrics.stop_atr_multiple:.2f}",
            "",
            f"**Initial Position**: {proposal.initial_position_pct:.2f}%",
            "",
            f"**Target Position**: {proposal.target_position_pct:.2f}%",
            "",
            f"**Initial Portfolio Risk (calculated)**: {metrics.initial_portfolio_risk_pct:.4f}%",
        ])
    parts.extend([
        "",
        f"FINAL TRANSACTION PROPOSAL: **{proposal.action.value.upper()}**",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Portfolio Manager
# ---------------------------------------------------------------------------


class PortfolioDecision(BaseModel):
    """Structured output produced by the Portfolio Manager.

    The model fills every field as part of its primary LLM call; no separate
    extraction pass is required. Field descriptions double as the model's
    output instructions, so the prompt body only needs to convey context and
    the rating-scale guidance.
    """

    model_config = ConfigDict(extra="forbid")

    rating: PortfolioRating = Field(
        description=(
            "The final position rating. Exactly one of Buy / Overweight / Hold / "
            "Underweight / Sell, picked based on the analysts' debate."
        ),
    )
    executive_summary: str = Field(
        description=(
            "A concise qualitative action plan. Two to four sentences. Do not "
            "state entry, stop, target, trigger, position sizing, risk levels, "
            "or other executable numbers here. Use no digits, currency symbols, "
            "percent signs, Chinese numeric characters, or ATR token; dedicated "
            "structured fields carry every executable value."
        ),
    )
    investment_thesis: str = Field(
        description=(
            "Detailed reasoning anchored in specific evidence from the analysts' "
            "debate. If prior lessons are referenced in the prompt context, "
            "incorporate them; otherwise rely solely on the current analysis. "
            "Describe the evidence directionally without digits, currency symbols, "
            "percent signs, Chinese numeric characters, or ATR token. Never place "
            "an executable value in prose."
        ),
    )
    price_target: float | None = Field(
        default=None,
        description="Optional target price in the instrument's quote currency.",
    )
    entry_price: float | None = Field(
        default=None,
        description="Required planned entry price for Buy or Overweight decisions.",
    )
    stop_loss: float | None = Field(
        default=None,
        description="Required hard stop price for Buy or Overweight decisions.",
    )
    target_position_pct: float | None = Field(
        default=None,
        description="Required final target position percent for Buy or Overweight.",
    )
    initial_position_pct: float | None = Field(
        default=None,
        description="Required initial position percent for Buy or Overweight.",
    )
    time_horizon: str | None = Field(
        default=None,
        description="Optional recommended holding period, e.g. '3-6 months'.",
    )

    @field_validator(
        "price_target", "entry_price", "stop_loss",
        "target_position_pct", "initial_position_pct",
        mode="before",
    )
    @classmethod
    def _nullish_float_to_none(cls, v):
        return _coerce_optional_float(v)

def render_pm_decision(
    decision: PortfolioDecision,
    *,
    verified_market: dict | None = None,
    risk_policy: dict | None = None,
    evidence_context: str | None = None,
) -> str:
    """Render a PortfolioDecision back to the markdown shape the rest of the system expects.

    Memory log, CLI display, and saved report files all read this markdown,
    so the rendered output preserves the exact section headers (``**Rating**``,
    ``**Executive Summary**``, ``**Investment Thesis**``) that downstream
    parsers and the report writers already handle.
    """
    metrics = None
    executive_summary = decision.executive_summary
    investment_thesis = decision.investment_thesis
    if decision.rating in {PortfolioRating.BUY, PortfolioRating.OVERWEIGHT}:
        from .trade_plan import validate_long_trade_plan

        if not verified_market or not risk_policy:
            raise ValueError("trusted market snapshot and server risk policy are required")

        executive_summary = _reject_calculated_trade_math(executive_summary)
        investment_thesis = _reject_calculated_trade_math(investment_thesis)

        metrics = validate_long_trade_plan(
            entry_price=decision.entry_price,
            stop_loss=decision.stop_loss,
            price_target=decision.price_target,
            target_position_pct=decision.target_position_pct,
            initial_position_pct=decision.initial_position_pct,
            verified_close=verified_market["close"],
            verified_atr=verified_market["atr"],
            max_portfolio_risk_pct=risk_policy["max_portfolio_risk_pct"],
            max_position_pct=risk_policy["max_position_pct"],
            max_notional_exposure_pct=risk_policy["max_notional_exposure_pct"],
            available_buying_power_pct=risk_policy["available_buying_power_pct"],
            allow_new_long_positions=risk_policy["allow_new_long_positions"],
            max_entry_deviation_pct=risk_policy["max_entry_deviation_pct"],
        )
    else:
        from .trade_plan import reject_numeric_plan_fields

        reject_numeric_plan_fields(
            entry_price=decision.entry_price,
            stop_loss=decision.stop_loss,
            price_target=decision.price_target,
            target_position_pct=decision.target_position_pct,
            initial_position_pct=decision.initial_position_pct,
        )
        executive_summary = _sanitize_non_executable_prose(executive_summary)
        investment_thesis = _sanitize_non_executable_prose(investment_thesis)
    _validate_currency_evidence(
        f"{executive_summary}\n{investment_thesis}",
        evidence_context,
    )
    parts = [
        f"**Rating**: {decision.rating.value}",
        "",
        f"**Executive Summary**: {executive_summary}",
        "",
        f"**Investment Thesis**: {investment_thesis}",
    ]
    if decision.price_target is not None:
        parts.extend(["", f"**Price Target**: {decision.price_target}"])
    if metrics is not None:
        parts.extend([
            "",
            f"**Entry Price**: {decision.entry_price}",
            "",
            f"**Stop Loss**: {decision.stop_loss}",
            "",
            f"**Verified Market Date**: {verified_market['market_date']}",
            "",
            f"**Verified Close**: {verified_market['close']}",
            "",
            f"**Verified ATR**: {verified_market['atr']}",
            "",
            f"**Market Data Call ID**: {verified_market['vendor_call_id']}",
            "",
            f"**Reward/Risk (calculated)**: {metrics.reward_risk_ratio:.2f}",
            "",
            f"**Stop Distance (ATR, calculated)**: {metrics.stop_atr_multiple:.2f}",
            "",
            f"**Initial Position**: {decision.initial_position_pct:.2f}%",
            "",
            f"**Target Position**: {decision.target_position_pct:.2f}%",
            "",
            f"**Initial Portfolio Risk (calculated)**: {metrics.initial_portfolio_risk_pct:.4f}%",
            "",
            f"**Maximum Portfolio Risk**: {risk_policy['max_portfolio_risk_pct']:.4f}%",
            "",
            f"**Maximum Notional Exposure**: {risk_policy['max_notional_exposure_pct']:.2f}%",
        ])
    if decision.time_horizon:
        parts.extend(["", f"**Time Horizon**: {decision.time_horizon}"])
    return "\n".join(parts)


def render_review_required(*, stage: str, reason: str) -> str:
    """Render an operational no-decision without disguising it as Hold.

    A genuine Hold is an investment conclusion. Validation or structured-output
    failure is instead a first-class absence of an authorised decision.
    """
    return "\n".join([
        "**Decision Status**: REVIEW_REQUIRED",
        "",
        "**Decision**: NO_DECISION",
        "",
        f"**Failed Stage**: {stage}",
        "",
        f"**Reason**: {reason}",
        "",
        "**Trading Authorization**: DENIED",
    ])


# ---------------------------------------------------------------------------
# Sentiment Analyst
# ---------------------------------------------------------------------------


class SentimentBand(str, Enum):
    """Discrete sentiment direction produced by the Sentiment Analyst.

    Six tiers keep the signal granular enough to be actionable while remaining
    small enough for every provider to map reliably from its JSON output.
    """

    BULLISH = "Bullish"
    MILDLY_BULLISH = "Mildly Bullish"
    NEUTRAL = "Neutral"
    MIXED = "Mixed"
    MILDLY_BEARISH = "Mildly Bearish"
    BEARISH = "Bearish"


class SentimentReport(BaseModel):
    """Structured sentiment report produced by the Sentiment Analyst.

    Replaces the previous free-form prose output so downstream consumers
    (dashboards, audit logs, PDF renderers, other agents) can read
    ``overall_band`` and ``overall_score`` without maintaining fragile regex
    fallbacks that drift with every model release. ``narrative`` preserves the
    rich source-by-source analysis; ``render_sentiment_report`` prepends a
    deterministic header so the saved report stays human-readable.
    """

    model_config = ConfigDict(extra="forbid")

    overall_band: SentimentBand = Field(
        description=(
            "Overall sentiment direction. Exactly one of: "
            "Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish. "
            "Use Mixed when sources point in clearly different directions. "
            "Use Neutral only when all sources are genuinely silent or non-committal."
        ),
    )
    overall_score: float = Field(
        ge=0.0,
        le=10.0,
        description=(
            "Numeric sentiment intensity on a 0–10 scale. "
            "0 = maximally bearish, 5 = neutral, 10 = maximally bullish. "
            "Guideline for consistency with overall_band: "
            "Bullish ~6.5–10, Mildly Bullish ~5.5–6.4, Neutral/Mixed ~4.5–5.5, "
            "Mildly Bearish ~3.5–4.4, Bearish ~0–3.4. "
            "Only the 0–10 bounds are enforced."
        ),
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description=(
            "Confidence in the assessment based on data quality and sample size. "
            "Use 'low' when one or more sources returned a placeholder or fewer "
            "than 5 data points; 'medium' when data is present but sparse; "
            "'high' when all three sources returned substantive data."
        ),
    )
    narrative: str = Field(
        description=(
            "Full sentiment report covering, in order: "
            "(1) source-by-source breakdown with specific evidence (cite message "
            "counts, ratios, notable posts); "
            "(2) cross-source divergences and alignments; "
            "(3) dominant narrative themes; "
            "(4) catalysts and risks surfaced by the data; "
            "(5) a markdown table summarising key sentiment signals, their "
            "direction, source, and supporting evidence. "
            "Keep it informative and substantive: develop each section thoroughly "
            "with concrete evidence so every point adds new signal for the trader."
        ),
    )


def render_sentiment_report(report: SentimentReport) -> str:
    """Render a SentimentReport to the markdown shape the rest of the system expects.

    The structured header (band + score + confidence) is prepended to the
    narrative so the saved report is both human-readable and machine-parseable
    without regex.
    """
    return "\n".join([
        f"**Overall Sentiment:** **{report.overall_band.value}** "
        f"(Score: {report.overall_score:.1f}/10)",
        f"**Confidence:** {report.confidence.capitalize()}",
        "",
        report.narrative,
    ])
