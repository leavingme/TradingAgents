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

import pandas as pd

MAX_STALE_DAYS = 10  # matches stockstats_utils.MAX_OHLCV_STALE_DAYS

_MARKET_TIMEZONES = {
    "_HK": "Asia/Hong_Kong",
    "_SH": "Asia/Shanghai",
    "_SZ": "Asia/Shanghai",
    "_BJ": "Asia/Shanghai",
    "_US": "America/New_York",
}


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
    return None


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
    combined = normalize_ohlcv_dates(combined, cache_key)
    combined = (
        combined.dropna(subset=["Date"])
        .drop_duplicates(subset=["Date"])
        .sort_values("Date")
        .reset_index(drop=True)
    )
    os.makedirs(cache_dir, exist_ok=True)
    combined.to_csv(path, index=False, encoding="utf-8")
