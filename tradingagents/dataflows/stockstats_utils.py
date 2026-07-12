import logging
import os
import time
from typing import Annotated

import pandas as pd
from stockstats import wrap

from .config import get_config
from .symbol_utils import NoMarketDataError, normalize_symbol
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)

# A vendor's latest OHLCV row this many calendar days before the requested date
# is treated as stale. Generous enough to span long holiday weekends, tight
# enough to catch the year-old frames westock occasionally returns (#1021).
MAX_OHLCV_STALE_DAYS = 10


def _ensure_date_column(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize the date column to ``Date``.

    Some westock builds leave the index unnamed (so ``reset_index()`` yields
    ``index``) or use ``Datetime`` for intraday data. Rename the first
    date-like column so indicators don't silently drop when it isn't ``Date``.
    """
    if "Date" in data.columns:
        return data
    for candidate in ("index", "Datetime", "date"):
        if candidate in data.columns:
            return data.rename(columns={candidate: "Date"})
    return data


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize a stock DataFrame for stockstats: parse dates, drop invalid rows, fill price gaps."""
    data = _ensure_date_column(data)
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["Close"])
    data[price_cols] = data[price_cols].ffill().bfill()

    return data


def _coerce_ohlcv_dates(data: pd.DataFrame) -> pd.Series:
    """Return parsed dates from an OHLCV frame, whether Date is a column or the index."""
    if "Date" in data.columns:
        return pd.to_datetime(data["Date"], errors="coerce").dropna()
    # westock keeps the dates in the index (a DatetimeIndex, sometimes unnamed).
    if isinstance(data.index, pd.DatetimeIndex):
        return pd.Series(pd.to_datetime(data.index, errors="coerce")).dropna()
    # Fallback: expose the index and look for any date-like column.
    df = data.reset_index()
    for col in ("Date", "Datetime", "date", "index"):
        if col in df.columns:
            parsed = pd.to_datetime(df[col], errors="coerce").dropna()
            if not parsed.empty:
                return parsed
    return pd.Series(dtype="datetime64[ns]")


def _assert_ohlcv_not_stale(
    data: pd.DataFrame,
    curr_date: str,
    symbol: str,
    canonical: str | None = None,
    *,
    max_stale_days: int = MAX_OHLCV_STALE_DAYS,
) -> None:
    """Reject OHLCV whose latest row is far older than curr_date.

    Raises NoMarketDataError (with a stale-specific detail) so the router treats
    it like any other "no usable data from this vendor" — try the next vendor,
    then emit one clear unavailable signal. Empty frames are left to the
    caller's existing no-data handling; this guards only the dangerous case of
    present-but-stale rows (a vendor returning a year-old frame that would
    otherwise feed wrong prices to the agent, #1021).
    """
    if data is None or data.empty:
        return
    requested = pd.to_datetime(curr_date, errors="coerce")
    if pd.isna(requested):
        return
    requested = requested.normalize()
    dates = _coerce_ohlcv_dates(data)
    if dates.empty:
        return
    latest = dates.max().normalize()
    stale_days = (requested - latest).days
    if stale_days > max_stale_days:
        raise NoMarketDataError(
            symbol,
            canonical,
            f"latest row is {latest.date()}, {stale_days} days before the "
            f"requested {requested.date()} (stale) — refusing to use it",
        )


def load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV data with caching, filtered to prevent look-ahead bias.

    Downloads 5 years of data up to today and merges into a per-symbol cache
    file (~/.tradingagents/cache/{SYMBOL}.csv).  On subsequent calls the
    cached rows are reused; only when the latest cached row is more than
    MAX_OHLCV_STALE_DAYS behind curr_date is a fresh download triggered and
    merged back into the file.
    """
    from .ohlcv_cache import (
        symbol_to_cache_key,
        read_cached_ohlcv,
        normalize_ohlcv_dates,
        filter_completed_daily_bars,
        parse_ohlcv_payload,
    )

    # Resolve broker/forex symbols (XAUUSD+ -> GC=F) to Westock's convention,
    # then reject values that would escape the cache directory when
    # interpolated into the cache filename (e.g. ``../../tmp/x``).
    canonical = normalize_symbol(symbol)
    safe_symbol = safe_ticker_component(canonical)
    cache_key = symbol_to_cache_key(safe_symbol)

    config = get_config()
    cache_dir = config["data_cache_dir"]

    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y-%m-%d")
    # westock ``end`` is EXCLUSIVE; request tomorrow so today's row is included
    # when curr_date is the current day (#986).
    end_str = (today_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    curr_date_dt = pd.to_datetime(curr_date)

    # --- cache read ---
    cached = read_cached_ohlcv(cache_dir, cache_key, start_str, curr_date)
    if cached is not None:
        data = _clean_dataframe(cached)
        data = data[data["Date"] <= curr_date_dt]
        _assert_ohlcv_not_stale(data, curr_date, symbol, canonical)
        return data

    # Fetch through the configured core-stock chain. The default order is
    # Longbridge MCP, Longbridge CLI, then Westock; indicator computation must
    # consume the same canonical OHLCV source as the market analyst.
    try:
        from .interface import route_to_vendor
        raw = route_to_vendor("get_stock_data", symbol, start_str, curr_date)
        downloaded = parse_ohlcv_payload(raw)
    except Exception as exc:
        logger.error("Configured OHLCV chain failed: %s", exc)
        raise NoMarketDataError(symbol, canonical, f"no market data available: {exc}") from exc

    # Ensure Date column standard layout
    downloaded = _ensure_date_column(downloaded)
    downloaded = normalize_ohlcv_dates(downloaded, cache_key)
    downloaded = filter_completed_daily_bars(downloaded, cache_key)
    if downloaded.empty or "Close" not in downloaded.columns:
        raise NoMarketDataError(
            symbol, canonical, "No market data returned"
        )

    data = _clean_dataframe(downloaded)
    data = data[data["Date"] <= curr_date_dt]
    _assert_ohlcv_not_stale(data, curr_date, symbol, canonical)
    return data


def filter_financials_by_date(data: pd.DataFrame, curr_date: str) -> pd.DataFrame:
    """Drop financial statement columns (fiscal period timestamps) after curr_date.

    westock financial statements use fiscal period end dates as columns.
    Columns after curr_date represent future data and are removed to
    prevent look-ahead bias.
    """
    if not curr_date or data.empty:
        return data
    cutoff = pd.Timestamp(curr_date)
    mask = pd.to_datetime(data.columns, errors="coerce") <= cutoff
    return data.loc[:, mask]


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "ticker symbol for the company"],
        indicator: Annotated[
            str, "quantitative indicators based off of the stock data for the company"
        ],
        curr_date: Annotated[
            str, "curr date for retrieving stock price data, YYYY-mm-dd"
        ],
        calculation_start: str | None = None,
    ):
        data = load_ohlcv(symbol, curr_date)
        if calculation_start:
            data = data[data["Date"] >= pd.Timestamp(calculation_start)].copy()
            if data.empty:
                raise NoMarketDataError(
                    symbol,
                    detail=(
                        "No OHLCV rows on or after calculation start "
                        f"{calculation_start}"
                    ),
                )
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")

        df[indicator]  # trigger stockstats to calculate the indicator
        matching_rows = df[df["Date"].str.startswith(curr_date_str)]

        if not matching_rows.empty:
            indicator_value = matching_rows[indicator].values[0]
            return indicator_value
        else:
            return "N/A: Not a trading day (weekend or holiday)"
