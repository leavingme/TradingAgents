"""Deterministic history requirements for technical indicators."""

from __future__ import annotations

import math


_ALIASES = {
    "macds": "macd",
    "macdh": "macd",
    "boll_ub": "boll",
    "boll_lb": "boll",
    "sma50": "close_50_sma",
}

# Trading bars required before an indicator can produce a meaningful value.
# These are calculation requirements, not LLM-selected display windows.
_WARMUP_TRADING_BARS = {
    "close_10_ema": 10,
    "close_50_sma": 50,
    "close_200_sma": 200,
    "sma": 20,
    "ema": 10,
    "macd": 35,  # 26-period slow EMA plus 9-period signal warm-up
    "rsi": 14,
    "atr": 14,
    "vwma": 20,
    "boll": 20,
}

# Longbridge Pine and Westock/stockstats must start on the same date so their
# recursive indicators have the same seed horizon. Three years supplies about
# 750 US trading bars while keeping online quant requests bounded.
INDICATOR_CALCULATION_HISTORY_DAYS = 1095


def canonical_indicator(indicator: str) -> str:
    key = str(indicator).lower().strip()
    return _ALIASES.get(key, key)


def indicator_warmup_bars(indicator: str) -> int:
    """Return the minimum source trading bars needed for calculation."""
    return _WARMUP_TRADING_BARS.get(canonical_indicator(indicator), 1)


def minimum_indicator_lookback_days(indicator: str) -> int:
    """Convert required trading bars to a conservative calendar-day window.

    The 3/2 conversion covers weekends and ordinary exchange holidays; seven
    extra calendar days cover a long holiday closure without relying on the
    model to request a sufficiently large window.
    """
    bars = indicator_warmup_bars(indicator)
    return max(1, math.ceil(bars * 3 / 2) + 7)


def effective_indicator_lookback_days(indicator: str, requested_days: int) -> int:
    """Never allow an LLM-selected window below the calculation requirement."""
    return max(int(requested_days), minimum_indicator_lookback_days(indicator))


def indicator_calculation_lookback_days(indicator: str, requested_days: int) -> int:
    """Return the shared vendor-neutral indicator calculation horizon.

    ``requested_days`` remains the output/display window.  This function only
    controls how much earlier source history is supplied to calculation
    engines. Longbridge Pine and Westock must both use the resulting start date.
    """
    minimum = minimum_indicator_lookback_days(indicator)
    return max(int(requested_days), minimum, INDICATOR_CALCULATION_HISTORY_DAYS)
