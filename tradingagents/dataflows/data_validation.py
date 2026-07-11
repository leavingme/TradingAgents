"""Deterministic validation for data returned by vendor implementations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from io import StringIO
import re

import pandas as pd


class ValidationStatus(str, Enum):
    VERIFIED = "verified"
    INVALID = "invalid"


@dataclass(frozen=True)
class ValidationResult:
    status: ValidationStatus
    detail: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.status is ValidationStatus.VERIFIED


@dataclass(frozen=True)
class IndicatorObservation:
    date: pd.Timestamp
    value: float


@dataclass(frozen=True)
class NormalizedIndicatorData:
    indicator: str
    analysis_date: pd.Timestamp
    observations: tuple[IndicatorObservation, ...]
    summary_values: tuple[float, ...] = ()
    bars: int | None = None
    source_text: str = ""


def _parse_ohlcv(payload: object) -> pd.DataFrame:
    if isinstance(payload, pd.DataFrame):
        return payload.copy()
    if not isinstance(payload, str):
        return pd.DataFrame()
    lines = []
    for line in payload.strip().splitlines():
        if line.startswith("#") or (line and all(ch in "─-= \t" for ch in line)):
            continue
        lines.append(line)
    header = next((line for line in lines if line.lstrip().lower().startswith("date")), None)
    if header is None:
        return pd.DataFrame()
    try:
        return pd.read_csv(
            StringIO("\n".join(lines)),
            sep=r"\s+" if "," not in header else ",",
            engine="python",
        )
    except Exception:
        return pd.DataFrame()


def _validate_ohlcv(payload: object) -> ValidationResult:
    frame = _parse_ohlcv(payload)
    frame = frame.rename(columns={column: str(column).strip() for column in frame.columns})
    column_lookup = {column.lower(): column for column in frame.columns}
    canonical_names = {
        name: column_lookup[name.lower()]
        for name in ("Date", "Open", "High", "Low", "Close", "Volume")
        if name.lower() in column_lookup
    }
    frame = frame.rename(columns={source: target for target, source in canonical_names.items()})
    required = ("Date", "Open", "High", "Low", "Close", "Volume")
    if frame.empty:
        return ValidationResult(ValidationStatus.INVALID, "empty or unparseable OHLCV payload")
    if missing := [column for column in required if column not in frame.columns]:
        return ValidationResult(ValidationStatus.INVALID, f"missing OHLCV columns: {', '.join(missing)}")
    dates = pd.to_datetime(frame["Date"], errors="coerce")
    numeric = frame[list(required[1:])].apply(pd.to_numeric, errors="coerce")
    if dates.isna().any() or numeric.isna().any().any():
        return ValidationResult(ValidationStatus.INVALID, "OHLCV contains invalid dates or numbers")
    if (numeric[["Open", "High", "Low", "Close"]] <= 0).any().any():
        return ValidationResult(ValidationStatus.INVALID, "OHLC prices must be positive")
    if (numeric["Volume"] < 0).any():
        return ValidationResult(ValidationStatus.INVALID, "volume must not be negative")
    if (numeric["Low"] > numeric[["Open", "Close", "High"]].min(axis=1)).any():
        return ValidationResult(ValidationStatus.INVALID, "low exceeds another OHLC value")
    if (numeric["High"] < numeric[["Open", "Close", "Low"]].max(axis=1)).any():
        return ValidationResult(ValidationStatus.INVALID, "high is below another OHLC value")

    amount_column = next(
        (column_lookup[name] for name in ("amount", "turnover") if name in column_lookup),
        None,
    )
    if amount_column is not None:
        amount = pd.to_numeric(frame[amount_column], errors="coerce")
        if amount.isna().any():
            return ValidationResult(ValidationStatus.INVALID, "amount contains invalid numbers")
        if (amount < 0).any():
            return ValidationResult(ValidationStatus.INVALID, "amount must not be negative")
        positive_volume = numeric["Volume"] > 0
        implied_price = amount[positive_volume] / numeric.loc[positive_volume, "Volume"]
        minimum = numeric.loc[positive_volume, "Low"] * 0.5
        maximum = numeric.loc[positive_volume, "High"] * 2.0
        if ((implied_price < minimum) | (implied_price > maximum)).any():
            return ValidationResult(
                ValidationStatus.INVALID,
                "amount/volume implied price is outside the allowed OHLC range",
            )
        if ((numeric["Volume"] == 0) & (amount != 0)).any():
            return ValidationResult(
                ValidationStatus.INVALID,
                "amount must be zero when volume is zero",
            )
    return ValidationResult(ValidationStatus.VERIFIED)


def validate_vendor_result(method: str, payload: object) -> ValidationResult:
    """Apply method-specific validation before a routed result is accepted."""
    if payload is None:
        return ValidationResult(ValidationStatus.INVALID, "vendor returned None")
    if isinstance(payload, str):
        value = payload.strip()
        if not value or value.startswith(("NO_DATA_AVAILABLE:", "DATA_UNAVAILABLE:")):
            return ValidationResult(ValidationStatus.INVALID, "vendor returned no usable data")
    elif hasattr(payload, "empty") and payload.empty:
        return ValidationResult(ValidationStatus.INVALID, "vendor returned empty data")
    elif isinstance(payload, (list, tuple, dict, set)) and not payload:
        return ValidationResult(ValidationStatus.INVALID, "vendor returned an empty collection")
    if method == "get_stock_data":
        return _validate_ohlcv(payload)
    return ValidationResult(ValidationStatus.VERIFIED)


_PRICE_INDICATORS = {
    "close_10_ema", "close_50_sma", "close_200_sma",
    "sma", "sma50", "ema", "vwma", "boll", "boll_ub", "boll_lb",
}
_MIN_BARS = {
    "close_10_ema": 10,
    "close_50_sma": 50,
    "sma50": 50,
    "close_200_sma": 200,
    "rsi": 14,
    "atr": 14,
    "vwma": 20,
    "boll": 20,
    "boll_ub": 20,
    "boll_lb": 20,
}


def _parse_indicator_payload(
    payload: object,
) -> tuple[list[tuple[pd.Timestamp, float]], list[float], int | None]:
    text = str(payload)
    observations: list[tuple[pd.Timestamp, float]] = []
    summary_values: list[float] = []
    bars: int | None = None

    for line in text.splitlines():
        dated = re.match(
            r"^\s*(\d{4}-\d{2}-\d{2})\s*:\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$",
            line,
        )
        if dated:
            observations.append((pd.Timestamp(dated.group(1)), float(dated.group(2))))
            continue
        summary = re.search(
            r"last=([-+]?\d+(?:\.\d+)?)\s+range=\[([-+]?\d+(?:\.\d+)?),\s*"
            r"([-+]?\d+(?:\.\d+)?)\]\s+bars=(\d+)",
            line,
        )
        if summary:
            summary_values.extend(float(summary.group(index)) for index in (1, 2, 3))
            parsed_bars = int(summary.group(4))
            bars = parsed_bars if bars is None else min(bars, parsed_bars)

    return observations, summary_values, bars


def normalize_indicator_result(
    payload: object,
    indicator: str,
    analysis_date: str,
) -> NormalizedIndicatorData:
    """Normalize every vendor format before any indicator validation occurs."""
    parsed_observations, summary_values, bars = _parse_indicator_payload(payload)
    observations = tuple(
        IndicatorObservation(date=date, value=value)
        for date, value in parsed_observations
    )
    return NormalizedIndicatorData(
        indicator=indicator.lower().strip(),
        analysis_date=pd.Timestamp(analysis_date),
        observations=observations,
        summary_values=tuple(summary_values),
        bars=bars,
        source_text=str(payload),
    )


def validate_indicator_result(
    payload: object | NormalizedIndicatorData,
    indicator: str | None = None,
    analysis_date: str | None = None,
    reference_close: float | None = None,
) -> ValidationResult:
    """Validate a technical-indicator payload against deterministic bounds."""
    normalized = (
        payload
        if isinstance(payload, NormalizedIndicatorData)
        else normalize_indicator_result(payload, indicator or "", analysis_date or "")
    )
    base = validate_vendor_result("_generic", normalized.source_text)
    if not base.is_valid:
        return base
    text = normalized.source_text.strip()
    lowered = text.lower()
    if any(marker in lowered for marker in (
        "error:", "error retrieving", "no data", "not directly available",
        "no series extracted", "empty series", "unexpected raw",
    )):
        return ValidationResult(ValidationStatus.INVALID, "indicator vendor returned an error or no data")

    key = normalized.indicator
    values = [observation.value for observation in normalized.observations]
    values.extend(normalized.summary_values)
    dates = [observation.date for observation in normalized.observations]
    bars = normalized.bars
    if not values:
        return ValidationResult(ValidationStatus.INVALID, "indicator payload contains no parseable values")
    series = pd.Series(values, dtype="float64")
    if not pd.Series(series).map(lambda value: pd.notna(value) and abs(value) != float("inf")).all():
        return ValidationResult(ValidationStatus.INVALID, "indicator contains non-finite values")
    cutoff = normalized.analysis_date
    if dates and max(dates) > cutoff:
        return ValidationResult(ValidationStatus.INVALID, "indicator contains values after the analysis date")
    report_date = re.search(r"Report Date:\s*(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
    if report_date and pd.Timestamp(report_date.group(1)) > cutoff:
        return ValidationResult(ValidationStatus.INVALID, "indicator report date is after the analysis date")
    minimum_bars = _MIN_BARS.get(key)
    if bars is not None and minimum_bars is not None and bars < minimum_bars:
        return ValidationResult(
            ValidationStatus.INVALID,
            f"indicator history has {bars} bars; at least {minimum_bars} are required",
        )
    if key == "rsi" and ((series < 0) | (series > 100)).any():
        return ValidationResult(ValidationStatus.INVALID, "RSI must be between 0 and 100")
    if key == "atr" and (series < 0).any():
        return ValidationResult(ValidationStatus.INVALID, "ATR must not be negative")
    if key in _PRICE_INDICATORS:
        if not normalized.observations:
            return ValidationResult(
                ValidationStatus.INVALID,
                "price indicator payload has no dated observations",
            )
        if reference_close is None or reference_close <= 0:
            return ValidationResult(ValidationStatus.INVALID, "verified Close is required for price indicator validation")
        observation_series = pd.Series(
            [observation.value for observation in normalized.observations],
            dtype="float64",
        )
        if (observation_series == 0).mean() > 0.2:
            return ValidationResult(ValidationStatus.INVALID, "price indicator zero ratio exceeds 20%")
        if len(observation_series) >= 10 and observation_series.value_counts(normalize=True).iloc[0] > 0.8:
            return ValidationResult(ValidationStatus.INVALID, "price indicator has excessive repeated values")
        nonzero = observation_series[observation_series != 0].abs()
        if len(nonzero) >= 2:
            adjacent_ratio = nonzero / nonzero.shift(1)
            if ((adjacent_ratio > 10) | (adjacent_ratio < 0.1)).any():
                return ValidationResult(
                    ValidationStatus.INVALID,
                    "price indicator jumps across an order of magnitude",
                )
        if ((series < 0.2 * reference_close) | (series > 5.0 * reference_close)).any():
            return ValidationResult(
                ValidationStatus.INVALID,
                "price indicator is outside the allowed range relative to Close",
            )
    return ValidationResult(ValidationStatus.VERIFIED)


def indicator_requires_close(indicator: str) -> bool:
    return indicator.lower().strip() in _PRICE_INDICATORS


def latest_verified_close(payload: object, analysis_date: str) -> float:
    """Extract the latest Close on or before the analysis date from valid OHLCV."""
    validation = _validate_ohlcv(payload)
    if not validation.is_valid:
        raise ValueError(validation.detail or "invalid OHLCV")
    frame = _parse_ohlcv(payload)
    lookup = {str(column).strip().lower(): column for column in frame.columns}
    dates = pd.to_datetime(frame[lookup["date"]], errors="coerce")
    closes = pd.to_numeric(frame[lookup["close"]], errors="coerce")
    eligible = pd.DataFrame({"Date": dates, "Close": closes})
    eligible = eligible[eligible["Date"] <= pd.Timestamp(analysis_date)].sort_values("Date")
    if eligible.empty:
        raise ValueError("OHLCV has no Close on or before the analysis date")
    return float(eligible.iloc[-1]["Close"])
