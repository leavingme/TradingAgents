"""Route the exact-price verification snapshot through configured providers."""

from __future__ import annotations

from contextvars import ContextVar
from datetime import timedelta
from io import StringIO

import pandas as pd

from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from tradingagents.dataflows.router import route_to_vendor
from tradingagents.dataflows.symbols import normalize_symbol

_LAST_ROW_COUNT: ContextVar[int | None] = ContextVar("market_snapshot_row_count", default=None)


def last_snapshot_row_count() -> int | None:
    return _LAST_ROW_COUNT.get()


def load_snapshot_ohlcv(symbol: str, as_of_date: str, fill_gaps: bool = False) -> pd.DataFrame:
    """Load enough routed daily bars for 200-session indicators and the snapshot."""
    end = pd.Timestamp(as_of_date).normalize()
    start = (end - timedelta(days=500)).strftime("%Y-%m-%d")
    payload = route_to_vendor("get_stock_data", symbol, start, end.strftime("%Y-%m-%d"))
    if payload.startswith("DATA_UNAVAILABLE:"):
        raise VendorUnavailableError(payload)
    if payload.startswith("NO_DATA_AVAILABLE:"):
        raise NoMarketDataError(symbol, normalize_symbol(symbol), payload)
    try:
        frame = pd.read_csv(StringIO(payload), comment="#")
    except (TypeError, ValueError, pd.errors.ParserError) as exc:
        raise VendorUnavailableError("Routed market data could not be parsed for snapshot verification.") from exc
    required = {"Date", "Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(frame.columns):
        raise VendorUnavailableError("Routed market data is missing OHLCV columns for snapshot verification.")
    frame = frame.loc[:, ["Date", "Open", "High", "Low", "Close", "Volume"]].copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    for column in ("Open", "High", "Low", "Close", "Volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["Date", "Close"])
    frame = frame[frame["Date"] <= end].sort_values("Date")
    if frame.empty:
        raise NoMarketDataError(symbol, normalize_symbol(symbol), "no routed price rows on or before the analysis date")
    _LAST_ROW_COUNT.set(len(frame))
    if fill_gaps:
        frame.loc[:, ["Open", "High", "Low", "Close", "Volume"]] = (
            frame.loc[:, ["Open", "High", "Low", "Close", "Volume"]].ffill().bfill()
        )
    return frame.reset_index(drop=True)
