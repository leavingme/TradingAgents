"""
Shared OHLCV disk-cache helpers used by all vendor modules.

Cache layout
------------
    {data_cache_dir}/{safe_symbol}.csv

One file per symbol. Rows are accumulated over time: when a request needs data
not yet in the cache, the vendor fetches from the API, the new rows are merged
(deduplicated by Date, sorted chronologically), and the file is rewritten.
Subsequent calls for the same or overlapping windows skip the network entirely.

Staleness
---------
The cache is considered stale when the latest row is more than MAX_STALE_DAYS
calendar days before the requested end_date.  For historical back-tests the
file is reused indefinitely; for live/recent queries it is refreshed when a
new trading day becomes available.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, time
from io import StringIO
from zoneinfo import ZoneInfo

import pandas as pd

MAX_STALE_DAYS = 10  # matches stockstats_utils.MAX_OHLCV_STALE_DAYS

_MARKET_TIMEZONES = {
    "_HK": "Asia/Hong_Kong",
    "_SH": "Asia/Shanghai",
    "_SZ": "Asia/Shanghai",
    "_BJ": "Asia/Shanghai",
    "_US": "America/New_York",
    "_SG": "Asia/Singapore",
}

# Conservative daily-bar completion cutoffs. The buffer avoids accepting a
# closing-auction/in-flight daily candle as final immediately at the nominal
# market close. Symbols without a market suffix use the US session because
# TradingAgents' bare ticker convention (NVDA, AAPL, ...) denotes US stocks.
_MARKET_CLOSES = {
    "_HK": time(16, 15),
    "_SH": time(15, 15),
    "_SZ": time(15, 15),
    "_BJ": time(15, 15),
    "_US": time(16, 15),
    "_SG": time(17, 15),
}
_DEFAULT_MARKET_TIMEZONE = "America/New_York"
_DEFAULT_MARKET_CLOSE = time(16, 15)
CANONICAL_OHLCV_COLUMNS = ["Date", "Open", "High", "Low", "Close", "Volume"]


def _is_equity_daily_cache_key(cache_key: str) -> bool:
    """Whether a cache key represents an exchange-listed equity-like symbol."""
    upper = cache_key.upper()
    if any(upper.endswith(suffix) for suffix in _MARKET_TIMEZONES):
        return True
    # Bare alphabetic tickers are US equities by TradingAgents convention.
    # Structural futures/forex/crypto keys (GC_F, EURUSD_X, BTC-USD) are not.
    return re.fullmatch(r"[A-Z]+", upper) is not None


def clean_canonical_daily_bars(data: pd.DataFrame, cache_key: str) -> pd.DataFrame:
    """Remove impossible dates and shifted duplicates from canonical daily bars.

    Older cache writers occasionally persisted one candle twice: once on an
    invalid weekend/holiday date and once on its real exchange trading date.
    A positive-volume daily equity candle cannot belong to a weekend. Exact
    adjacent OHLCV duplicates are likewise the same source candle with two
    date labels; keep the later label, which is the exchange trading date in
    the observed UTC-to-local shift pattern.
    """
    if data.empty or "Date" not in data.columns:
        return data

    out = data.copy().dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    if _is_equity_daily_cache_key(cache_key):
        out = out[out["Date"].dt.weekday < 5].copy().reset_index(drop=True)

    value_columns = [
        column
        for column in ("Open", "High", "Low", "Close", "Volume")
        if column in out.columns
    ]
    if len(value_columns) == 5 and len(out) > 1:
        next_values = out[value_columns].shift(-1)
        same_candle = out[value_columns].eq(next_values).all(axis=1)
        next_dates = out["Date"].shift(-1)
        adjacent = (next_dates - out["Date"]).dt.days.between(1, 4)
        positive_volume = pd.to_numeric(out["Volume"], errors="coerce").fillna(0) > 0
        out = out[~(same_candle & adjacent & positive_volume)].copy()

    return out.reset_index(drop=True)


def parse_ohlcv_payload(raw: object) -> pd.DataFrame:
    """Parse the CSV or text-table shapes returned by configured OHLCV vendors."""
    if isinstance(raw, pd.DataFrame):
        return raw.copy()
    if not raw:
        return pd.DataFrame(columns=CANONICAL_OHLCV_COLUMNS)

    lines = []
    for line in str(raw).strip().splitlines():
        if line.startswith("#"):
            continue
        if line and all(character in "─-= \t" for character in line):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    header_line = next(
        (line for line in cleaned.splitlines() if line.lstrip().lower().startswith("date")),
        None,
    )
    if header_line and "," not in header_line:
        try:
            return pd.read_csv(StringIO(cleaned), sep=r"\s+", engine="python")
        except Exception:
            pass
    return pd.read_csv(StringIO(cleaned))


def symbol_to_cache_key(symbol: str) -> str:
    """
    Convert a ticker symbol to a clean filesystem-safe cache key.

    Examples
    --------
        NVDA.US  -> NVDA_US
        1810.HK  -> 1810_HK
        700.HK   -> 0700_HK
        GC=F     -> GC_F
        ^GSPC    -> GSPC
        NVDA     -> NVDA
    """
    raw = str(symbol or "").strip().upper()
    hk_match = re.fullmatch(r"0*(\d+)[._]HK", raw)
    if hk_match:
        code = (hk_match.group(1).lstrip("0") or "0").zfill(4)
        return f"{code}_HK"

    key = re.sub(r"[^A-Za-z0-9_-]", "_", raw).strip("_")
    return key or "UNKNOWN"


def cache_filepath(cache_dir: str, cache_key: str) -> str:
    """Return the canonical cache path for a symbol cache key."""
    return os.path.join(cache_dir, f"{cache_key}.csv")


def _cache_filepaths(cache_dir: str, cache_key: str) -> list[str]:
    paths = [cache_filepath(cache_dir, cache_key)]
    hk_match = re.fullmatch(r"(0*\d+)_HK", cache_key.upper())
    if not hk_match or not os.path.isdir(cache_dir):
        return paths

    canonical_code = hk_match.group(1).lstrip("0") or "0"
    legacy_re = re.compile(rf"0*{re.escape(canonical_code)}_HK\.csv$", re.IGNORECASE)
    for filename in os.listdir(cache_dir):
        if legacy_re.fullmatch(filename):
            path = os.path.join(cache_dir, filename)
            if path not in paths:
                paths.append(path)
    return paths


def _timezone_for_cache_key(cache_key: str) -> str | None:
    upper = cache_key.upper()
    for suffix, timezone in _MARKET_TIMEZONES.items():
        if upper.endswith(suffix):
            return timezone
    return _DEFAULT_MARKET_TIMEZONE


def _market_close_for_cache_key(cache_key: str) -> time:
    upper = cache_key.upper()
    for suffix, close_at in _MARKET_CLOSES.items():
        if upper.endswith(suffix):
            return close_at
    return _DEFAULT_MARKET_CLOSE


def _local_now(cache_key: str, now: datetime | None = None) -> datetime:
    timezone = ZoneInfo(_timezone_for_cache_key(cache_key) or "UTC")
    if now is None:
        return datetime.now(timezone)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone)
    return now.astimezone(timezone)


def latest_completed_daily_bar_date(
    cache_key: str,
    now: datetime | None = None,
) -> pd.Timestamp:
    """Return the latest date whose daily candle can safely be treated as final.

    On a trading day, today's bar is excluded until a short post-close buffer
    has elapsed. Weekends roll back to Friday. Exchange holidays are handled by
    the provider returning no bar for that date.
    """
    local_now = _local_now(cache_key, now)
    candidate = pd.Timestamp(local_now.date())
    if local_now.time() < _market_close_for_cache_key(cache_key):
        candidate -= pd.Timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= pd.Timedelta(days=1)
    return candidate.normalize()


def filter_completed_daily_bars(
    data: pd.DataFrame,
    cache_key: str,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Remove future and still-forming current-session daily candles."""
    if data.empty or "Date" not in data.columns:
        return data
    out = normalize_ohlcv_dates(data, cache_key)
    out = clean_canonical_daily_bars(out, cache_key)
    cutoff = latest_completed_daily_bar_date(cache_key, now)
    return out[out["Date"] <= cutoff].copy()


def request_includes_live_session(
    cache_key: str,
    end_date: str,
    now: datetime | None = None,
) -> bool:
    """Whether a cache read must refresh because the requested window reaches today.

    A same-day request always refreshes. Before close this prevents a partial
    candle from entering analysis; after close it ensures a partial candle
    cached earlier is replaced by the final daily bar.
    """
    local_today = pd.Timestamp(_local_now(cache_key, now).date())
    requested_end = pd.to_datetime(end_date)
    if getattr(requested_end, "tz", None) is not None:
        requested_end = requested_end.tz_localize(None)
    return requested_end.normalize() >= local_today


def normalize_ohlcv_dates(data: pd.DataFrame, cache_key: str) -> pd.DataFrame:
    """Normalize Date values to exchange-local, timezone-naive trading dates.

    Longbridge daily bars for HK/CN can arrive as UTC timestamps for local
    midnight (for example 2026-07-07T16:00:00Z means 2026-07-08 in Hong Kong).
    Keeping those UTC calendar dates makes downstream indicators think the
    actual trading day is missing.  Naive date strings are left as-is because
    Westock already returns local trading dates.
    """
    if data.empty or "Date" not in data.columns:
        return data

    out = data.copy()
    raw = out["Date"]
    text = raw.astype(str)
    has_timezone = text.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False).any()

    if has_timezone:
        parsed = pd.to_datetime(raw, errors="coerce", utc=True)
        timezone = _timezone_for_cache_key(cache_key)
        if timezone:
            parsed = parsed.dt.tz_convert(timezone)
        out["Date"] = parsed.dt.tz_localize(None).dt.normalize()
    else:
        out["Date"] = pd.to_datetime(raw, errors="coerce").dt.normalize()

    return out


def _latest_expected_business_day(end_date: pd.Timestamp) -> pd.Timestamp:
    expected = end_date.normalize()
    while expected.weekday() >= 5:
        expected -= pd.Timedelta(days=1)
    return expected


def read_cached_ohlcv(
    cache_dir: str,
    cache_key: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame | None:
    """
    Return a DataFrame of OHLCV rows filtered to [start_date, end_date] if the
    cache file exists and is not stale; otherwise return None (cache miss).

    A 'fresh' cache means the file's latest row is within MAX_STALE_DAYS of
    end_date.  Historical queries (end_date well in the past) are served from
    cache indefinitely.
    """
    if request_includes_live_session(cache_key, end_date):
        return None

    paths = [path for path in _cache_filepaths(cache_dir, cache_key) if os.path.exists(path)]
    if not paths:
        return None
    frames = []
    for path in paths:
        try:
            frames.append(pd.read_csv(path, on_bad_lines="skip", encoding="utf-8"))
        except Exception:
            continue
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    if df.empty or "Close" not in df.columns or "Date" not in df.columns:
        return None

    df = normalize_ohlcv_dates(df, cache_key)
    df = clean_canonical_daily_bars(df, cache_key)
    df = (
        df.dropna(subset=["Date"])
        .drop_duplicates(subset=["Date"], keep="last")
        .sort_values("Date")
        .reset_index(drop=True)
    )

    req_end = pd.to_datetime(end_date)
    if hasattr(req_end, "tz") and req_end.tz is not None:
        req_end = req_end.tz_localize(None)

    latest = df["Date"].max()

    if (req_end - latest).days > MAX_STALE_DAYS:
        return None  # stale: needs a fresh fetch
    if latest < _latest_expected_business_day(req_end):
        return None  # recent cache is incomplete: fetch missing trading days

    req_start = pd.to_datetime(start_date)
    if hasattr(req_start, "tz") and req_start.tz is not None:
        req_start = req_start.tz_localize(None)

    window = df[(df["Date"] >= req_start) & (df["Date"] <= req_end)].copy()
    return window if not window.empty else None


def merge_and_write_ohlcv(
    cache_dir: str,
    cache_key: str,
    new_df: pd.DataFrame,
) -> None:
    """
    Merge new_df into the cache file (if any), deduplicate by Date, sort
    chronologically, and rewrite.

    new_df must contain at least: Date, Open, High, Low, Close, Volume.
    Extra columns are preserved but not guaranteed to survive deduplication.
    """
    path = cache_filepath(cache_dir, cache_key)
    frames: list[pd.DataFrame] = []

    for existing_path in _cache_filepaths(cache_dir, cache_key):
        if not os.path.exists(existing_path):
            continue
        try:
            existing = pd.read_csv(existing_path, on_bad_lines="skip", encoding="utf-8")
            if not existing.empty and "Close" in existing.columns:
                frames.append(existing)
        except Exception:
            pass

    frames.append(new_df.copy())
    combined = pd.concat(frames, ignore_index=True)
    combined = filter_completed_daily_bars(combined, cache_key)
    available_columns = [column for column in CANONICAL_OHLCV_COLUMNS if column in combined.columns]
    combined = combined[available_columns]
    combined = (
        combined.dropna(subset=["Date"])
        .drop_duplicates(subset=["Date"], keep="last")
        .sort_values("Date")
        .reset_index(drop=True)
    )
    os.makedirs(cache_dir, exist_ok=True)
    combined.to_csv(path, index=False, encoding="utf-8")
