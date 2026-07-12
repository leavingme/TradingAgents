"""Deterministic validation and arithmetic for executable trade plans."""

from __future__ import annotations

from dataclasses import dataclass
import math


class TradePlanValidationError(ValueError):
    """Raised when an executable plan is incomplete or internally inconsistent."""


@dataclass(frozen=True)
class TradePlanMetrics:
    risk_per_share: float
    reward_per_share: float
    reward_risk_ratio: float
    stop_atr_multiple: float
    initial_portfolio_risk_pct: float


def reject_numeric_plan_fields(**values: float | None) -> None:
    supplied = [name for name, value in values.items() if value is not None]
    if supplied:
        raise TradePlanValidationError(
            "non-long decision must omit executable numeric fields until a "
            "direction-specific validator is available: " + ", ".join(supplied)
        )


def validate_long_trade_plan(
    *,
    entry_price: float | None,
    stop_loss: float | None,
    price_target: float | None,
    atr: float | None,
    target_position_pct: float | None,
    initial_position_pct: float | None,
    max_portfolio_risk_pct: float | None,
) -> TradePlanMetrics:
    values = {
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "price_target": price_target,
        "atr": atr,
        "target_position_pct": target_position_pct,
        "initial_position_pct": initial_position_pct,
        "max_portfolio_risk_pct": max_portfolio_risk_pct,
    }
    missing = [name for name, value in values.items() if value is None]
    if missing:
        raise TradePlanValidationError(
            "executable long plan missing structured fields: " + ", ".join(missing)
        )
    numeric = {name: float(value) for name, value in values.items()}
    if not all(math.isfinite(value) and value > 0 for value in numeric.values()):
        raise TradePlanValidationError("all executable trade-plan numbers must be finite and positive")
    entry = numeric["entry_price"]
    stop = numeric["stop_loss"]
    target = numeric["price_target"]
    if not stop < entry < target:
        raise TradePlanValidationError(
            f"long plan must satisfy stop_loss < entry_price < price_target; got {stop}, {entry}, {target}"
        )
    target_position = numeric["target_position_pct"]
    initial_position = numeric["initial_position_pct"]
    if target_position > 100 or initial_position > target_position:
        raise TradePlanValidationError(
            "position percentages must satisfy 0 < initial_position_pct <= target_position_pct <= 100"
        )
    risk = entry - stop
    reward = target - entry
    reward_risk = reward / risk
    stop_atr = risk / numeric["atr"]
    portfolio_risk = initial_position * (risk / entry)
    if portfolio_risk > numeric["max_portfolio_risk_pct"] + 1e-9:
        raise TradePlanValidationError(
            f"initial portfolio risk {portfolio_risk:.4f}% exceeds configured plan limit "
            f"{numeric['max_portfolio_risk_pct']:.4f}%"
        )
    return TradePlanMetrics(
        risk_per_share=risk,
        reward_per_share=reward,
        reward_risk_ratio=reward_risk,
        stop_atr_multiple=stop_atr,
        initial_portfolio_risk_pct=portfolio_risk,
    )
